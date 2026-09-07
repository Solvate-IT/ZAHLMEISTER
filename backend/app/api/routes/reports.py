import re
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_organization, get_session
from app.models.entities import Collection, CollectionParticipant, Organization, Participant, Payment
from app.services.reports import (
    CollectionReportData,
    CollectionReportRow,
    collection_csv,
    collection_pdf,
    collection_xlsx,
)

router = APIRouter(prefix="/collections", tags=["reports"])


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "collection"


@router.get("/{collection_id}/export")
async def export_collection(
    collection_id: UUID,
    format: str = Query(default="pdf", pattern="^(pdf|xlsx|csv)$"),
    detailed: bool = Query(default=False),
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> Response:
    collection = await session.get(Collection, collection_id)
    if collection is None or collection.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Collection not found")

    rows = (
        await session.execute(
            select(CollectionParticipant, Participant)
            .join(Participant, Participant.id == CollectionParticipant.participant_id)
            .where(CollectionParticipant.collection_id == collection.id)
            .order_by(Participant.name)
        )
    ).all()
    cp_ids = [cp.id for cp, _ in rows]
    latest_payments: dict[UUID, Payment] = {}
    if cp_ids:
        payments = (
            await session.execute(
                select(Payment)
                .where(Payment.collection_participant_id.in_(cp_ids))
                .order_by(Payment.booked_at.desc(), Payment.created_at.desc())
            )
        ).scalars().all()
        for payment in payments:
            latest_payments.setdefault(payment.collection_participant_id, payment)

    data = CollectionReportData(
        name=collection.name,
        locale=organization.locale,
        amount=Decimal(collection.amount),
        currency=collection.currency,
        due_at=collection.due_at,
        created_at=collection.created_at,
        rows=[
            CollectionReportRow(
                participant_name=participant.name,
                amount=Decimal(collection.amount),
                currency=collection.currency,
                status=cp.status,
                paid_at=cp.paid_at,
                payment_method=(latest_payments.get(cp.id).method if cp.id in latest_payments else None),
                payment_reference=cp.payment_reference,
                reminder_count=cp.reminder_count,
            )
            for cp, participant in rows
        ],
    )

    if format == "pdf":
        content = collection_pdf(data, detailed=detailed)
        media_type = "application/pdf"
    elif format == "xlsx":
        content = collection_xlsx(data, detailed=detailed)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content = collection_csv(data, detailed=detailed)
        media_type = "text/csv; charset=utf-8"

    suffix = "detail" if detailed else "summary"
    filename = f"{_safe_filename(collection.name)}_{suffix}.{format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
