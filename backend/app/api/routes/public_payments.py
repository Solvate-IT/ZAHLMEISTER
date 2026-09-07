import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import (
    Collection,
    CollectionParticipant,
    OnlinePaymentAttempt,
    OnlinePaymentConnection,
    Organization,
    Participant,
)
from app.schemas.online_payments import OnlineCheckoutRead
from app.schemas.payments import PublicPaymentRead
from app.services.mollie import PROVIDER, mollie_provider
from app.services.payments import epc_qr_payload, public_payment_url, render_qr_png

router = APIRouter(prefix="/public/payments", tags=["public-payments"])


async def _payment_row(session: AsyncSession, token: str, *, for_update: bool = False):
    statement = (
        select(CollectionParticipant, Collection, Participant, Organization)
        .join(Collection, Collection.id == CollectionParticipant.collection_id)
        .join(Participant, Participant.id == CollectionParticipant.participant_id)
        .join(Organization, Organization.id == Collection.organization_id)
        .where(CollectionParticipant.public_token == token)
    )
    if for_update:
        statement = statement.with_for_update(of=CollectionParticipant)
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    cp, collection, participant, organization = row
    if collection.status not in {"active", "completed"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not available")
    return cp, collection, participant, organization


async def _online_connection(session: AsyncSession, organization_id, *, for_update: bool = False):
    stmt = select(OnlinePaymentConnection).where(
        OnlinePaymentConnection.organization_id == organization_id,
        OnlinePaymentConnection.status == "connected",
        OnlinePaymentConnection.enabled.is_(True),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


@router.get("/{token}", response_model=PublicPaymentRead)
async def get_public_payment(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> PublicPaymentRead:
    cp, collection, participant, organization = await _payment_row(session, token)
    connection = await _online_connection(session, organization.id)
    bank_configured = bool(organization.bank_account_name and organization.bank_iban)
    if not bank_configured and connection is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment account unavailable")

    qr_data = None
    if bank_configured:
        qr_data = epc_qr_payload(
            account_name=organization.bank_account_name or "",
            iban=organization.bank_iban or "",
            bic=organization.bank_bic,
            amount=collection.amount,
            currency=collection.currency,
            reference=cp.payment_reference,
        )
    return PublicPaymentRead(
        collection_name=collection.name,
        participant_name=participant.name,
        amount=collection.amount,
        currency=collection.currency,
        status=cp.status,
        paid_at=cp.paid_at,
        account_name=organization.bank_account_name,
        iban=organization.bank_iban,
        bic=organization.bank_bic,
        payment_reference=cp.payment_reference,
        epc_qr_data=qr_data,
        online_payment_available=connection is not None,
        online_payment_provider=connection.provider if connection else None,
    )


@router.post("/{token}/online", response_model=OnlineCheckoutRead, status_code=201)
async def create_online_checkout(token: str) -> OnlineCheckoutRead:
    async with SessionLocal.begin() as session:
        cp, collection, participant, organization = await _payment_row(
            session, token, for_update=True
        )
        if cp.status == "paid":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment already received")
        connection = await _online_connection(session, organization.id)
        if connection is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Online payment unavailable")
        if connection.provider != PROVIDER:
            raise HTTPException(status_code=501, detail="Online payment provider is not supported")
        if not connection.profile_id:
            raise HTTPException(status_code=409, detail="Online payment profile is not selected")

        now = datetime.now(UTC)
        recent = await session.scalar(
            select(OnlinePaymentAttempt)
            .where(
                OnlinePaymentAttempt.collection_participant_id == cp.id,
                OnlinePaymentAttempt.connection_id == connection.id,
                OnlinePaymentAttempt.status.in_(["open", "pending"]),
                OnlinePaymentAttempt.checkout_url.is_not(None),
                OnlinePaymentAttempt.created_at >= now - timedelta(minutes=30),
            )
            .order_by(OnlinePaymentAttempt.created_at.desc())
            .limit(1)
        )
        if recent is not None and (recent.expires_at is None or recent.expires_at > now + timedelta(minutes=1)):
            return OnlineCheckoutRead(
                provider=recent.provider,
                checkout_url=recent.checkout_url or "",
                attempt_id=recent.id,
            )

        attempt = OnlinePaymentAttempt(
            organization_id=organization.id,
            collection_participant_id=cp.id,
            connection_id=connection.id,
            provider=connection.provider,
            webhook_key=secrets.token_urlsafe(32),
            status="creating",
            amount=collection.amount,
            currency=collection.currency,
        )
        session.add(attempt)
        await session.flush()

        redirect_url = f"{public_payment_url(settings.public_app_url, cp.public_token)}&online=return"
        webhook_url = (
            f"{settings.public_app_url.rstrip('/')}/api/v1/webhooks/mollie/{attempt.webhook_key}"
        )
        try:
            checkout = await mollie_provider.create_checkout(
                session,
                connection,
                amount=collection.amount,
                currency=collection.currency,
                description=f"{collection.name} · {cp.payment_reference}",
                redirect_url=redirect_url,
                webhook_url=webhook_url,
                metadata={
                    "zahlmeister_attempt_id": str(attempt.id),
                    "collection_participant_id": str(cp.id),
                    "payment_reference": cp.payment_reference,
                },
                locale=organization.locale,
                idempotency_key=str(attempt.id),
            )
        except Exception as exc:
            attempt.status = "failed"
            attempt.last_error = str(exc)[:2000]
            connection.last_error = attempt.last_error
            raise HTTPException(status_code=502, detail="Online payment could not be started") from exc

        attempt.external_id = checkout.external_id
        attempt.checkout_url = checkout.checkout_url
        attempt.status = checkout.status
        attempt.expires_at = checkout.expires_at
        connection.last_error = None
        return OnlineCheckoutRead(
            provider=connection.provider,
            checkout_url=checkout.checkout_url,
            attempt_id=attempt.id,
        )



@router.get("/{token}/qr.png", response_class=Response)
async def get_public_payment_qr(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    payment = await get_public_payment(token, session)
    if payment.epc_qr_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="SEPA QR not available"
        )
    try:
        png = await asyncio.to_thread(render_qr_png, payment.epc_qr_data)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="QR renderer unavailable"
        ) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )
