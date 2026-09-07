import json
import secrets
import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_organization, get_session
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import (
    Collection,
    CollectionParticipant,
    CommunicationChannelSetting,
    CommunicationConnection,
    CommunicationMessage,
    MessageTemplate,
    Organization,
    Participant,
    ParticipantList,
    Payment,
    ScheduledJob,
)
from app.schemas.workflow import (
    CollectionCreate,
    CollectionDetail,
    CollectionParticipantRead,
    CollectionRead,
    CollectionUpdate,
    PaymentStatusUpdate,
    QueueActionResult,
)
from app.services.channel_config import internal_channel_configured
from app.services.infobip import connection_is_active
from app.services.naming import unique_collection_name
from app.services.reminders import deserialize_reminder_rules, serialize_reminder_rules
from app.api.routes.message_templates import ensure_default_template
from app.services.templates import validate_template_body
from app.services.payments import epc_qr_payload, public_payment_qr_url, public_payment_url
from app.services.secrets import decrypt_config

router = APIRouter(prefix="/collections", tags=["collections"])


async def _owned_collection(
    session: AsyncSession,
    organization: Organization,
    collection_id: UUID,
    *,
    for_update: bool = False,
) -> Collection:
    item = await session.get(Collection, collection_id, with_for_update=for_update)
    if item is None or item.organization_id != organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    return item




async def _active_job_exists(
    session: AsyncSession, *, job_type: str, payload: str
) -> bool:
    job_id = await session.scalar(
        select(ScheduledJob.id)
        .where(
            ScheduledJob.job_type == job_type,
            ScheduledJob.payload == payload,
            ScheduledJob.status.in_(["pending", "running"]),
        )
        .limit(1)
    )
    return job_id is not None

def _require_bank_account(organization: Organization) -> None:
    if not organization.bank_account_name or not organization.bank_iban:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configure the receiving bank account before sending a collection",
        )




def _effective_message_options(item: Collection, organization: Organization) -> tuple[bool, bool]:
    include_link = (
        item.message_include_payment_link
        if item.message_include_payment_link is not None
        else organization.message_include_payment_link
    )
    include_qr = (
        item.message_include_payment_qr
        if item.message_include_payment_qr is not None
        else organization.message_include_payment_qr
    )
    return bool(include_link), bool(include_qr)


def _validate_message_options(include_link: bool, include_qr: bool) -> None:
    if not include_link and not include_qr:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enable at least the payment link or the payment QR code",
        )


def _payment_qr_url_if_available(
    *, organization: Organization, collection: Collection, cp: CollectionParticipant, enabled: bool
) -> str | None:
    if not enabled or not organization.bank_account_name or not organization.bank_iban:
        return None
    payload = epc_qr_payload(
        account_name=organization.bank_account_name,
        iban=organization.bank_iban,
        bic=organization.bank_bic,
        amount=collection.amount,
        currency=collection.currency,
        reference=cp.payment_reference,
    )
    if payload is None:
        return None
    return public_payment_qr_url(settings.public_app_url, cp.public_token)


def _summary(
    item: Collection, participant_count: int, paid_count: int, organization: Organization
) -> CollectionRead:
    return CollectionRead(
        id=item.id,
        name=item.name,
        participant_list_id=item.participant_list_id,
        amount=item.amount,
        currency=item.currency,
        send_at=item.send_at,
        due_at=item.due_at,
        status=item.status,
        participant_count=participant_count,
        paid_count=paid_count,
        paid_amount=item.amount * paid_count,
        communication_channel=item.communication_channel,
        communication_mode=item.communication_mode,
        message_template_id=item.message_template_id,
        message_body_override=item.message_body_override,
        reminder_rules=deserialize_reminder_rules(item.reminder_rules_json),
        include_payment_link=_effective_message_options(item, organization)[0],
        include_payment_qr=_effective_message_options(item, organization)[1],
    )


def _participant_read(
    *,
    cp: CollectionParticipant,
    participant: Participant,
    payment_method: str | None,
    delivery_status: str | None,
    communication_count: int = 0,
    payment_qr_url: str | None = None,
) -> CollectionParticipantRead:
    return CollectionParticipantRead(
        id=cp.id,
        participant_id=participant.id,
        name=participant.name,
        email=participant.email,
        phone=participant.phone,
        payment_reference=cp.payment_reference,
        payment_url=public_payment_url(settings.public_app_url, cp.public_token),
        payment_qr_url=payment_qr_url,
        status=cp.status,
        paid_at=cp.paid_at,
        payment_method=payment_method,
        initial_sent_at=cp.initial_sent_at,
        last_reminder_at=cp.last_reminder_at,
        reminder_count=cp.reminder_count,
        delivery_status=delivery_status,
        communication_count=communication_count,
    )


@router.get("", response_model=list[CollectionRead])
async def list_collections(
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> list[CollectionRead]:
    total_expr = func.count(CollectionParticipant.id)
    paid_expr = func.count(CollectionParticipant.id).filter(CollectionParticipant.status == "paid")
    stmt = (
        select(Collection, total_expr, paid_expr)
        .outerjoin(CollectionParticipant, CollectionParticipant.collection_id == Collection.id)
        .where(Collection.organization_id == organization.id)
        .group_by(Collection.id)
        .order_by(Collection.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [_summary(item, total, paid, organization) for item, total, paid in rows]


@router.post("", response_model=CollectionRead, status_code=status.HTTP_201_CREATED)
async def create_collection(
    payload: CollectionCreate,
    organization: Organization = Depends(get_organization),
) -> CollectionRead:
    now = datetime.now(UTC)
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        _require_bank_account(stored_org)

        participant_list = await session.get(
            ParticipantList, payload.participant_list_id, with_for_update=True
        )
        if participant_list is None or participant_list.organization_id != stored_org.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Participant list not found"
            )

        template = None
        if payload.message_template_id is not None:
            template = await session.get(MessageTemplate, payload.message_template_id)
            if template is None or template.organization_id != stored_org.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Message template not found"
                )
        else:
            template = await ensure_default_template(session, stored_org)
        if payload.message_body_override is not None:
            try:
                validate_template_body(payload.message_body_override)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
                ) from exc

        if payload.communication_mode == "external" and payload.send_at and payload.send_at > now:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="External communication must be sent manually and cannot be scheduled",
            )
        if payload.communication_mode == "internal":
            channel_setting = await session.scalar(
                select(CommunicationChannelSetting).where(
                    CommunicationChannelSetting.organization_id == stored_org.id,
                    CommunicationChannelSetting.channel == payload.communication_channel,
                    CommunicationChannelSetting.mode == "internal",
                )
            )
            if channel_setting is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Internal {payload.communication_channel} is not configured",
                )
            channel_config = decrypt_config(channel_setting.encrypted_config)
            connection = (
                await session.get(CommunicationConnection, channel_setting.connection_id)
                if channel_setting.connection_id
                else None
            )
            if not internal_channel_configured(
                payload.communication_channel,
                provider=channel_setting.provider,
                config=channel_config,
                connection_active=connection_is_active(connection),
                sender=channel_setting.sender,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Internal {payload.communication_channel} is not configured",
                )

        try:
            reminder_rules_json = serialize_reminder_rules(
                [rule.model_dump() for rule in payload.reminder_rules]
                if payload.reminder_rules is not None
                else None
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

        include_link = (
            payload.include_payment_link
            if payload.include_payment_link is not None
            else stored_org.message_include_payment_link
        )
        include_qr = (
            payload.include_payment_qr
            if payload.include_payment_qr is not None
            else stored_org.message_include_payment_qr
        )
        _validate_message_options(bool(include_link), bool(include_qr))

        name = await unique_collection_name(session, stored_org, payload.name)
        send_at = payload.send_at or now
        if payload.due_at is not None and payload.due_at.date() < send_at.date():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Due date must not be before the send date",
            )
        collection_status = ("active" if payload.communication_mode == "external" else ("scheduled" if send_at > now else "pending"))
        item = Collection(
            organization_id=stored_org.id,
            participant_list_id=participant_list.id,
            name=name,
            amount=payload.amount,
            currency=payload.currency or stored_org.currency,
            send_at=send_at,
            due_at=payload.due_at,
            status=collection_status,
            communication_channel=payload.communication_channel,
            communication_mode=payload.communication_mode,
            message_template_id=template.id,
            message_body_override=(payload.message_body_override.strip() if payload.message_body_override else None),
            reminder_rules_json=reminder_rules_json,
            message_include_payment_link=payload.include_payment_link,
            message_include_payment_qr=payload.include_payment_qr,
        )
        session.add(item)
        await session.flush()

        participants = (
            await session.execute(
                select(Participant)
                .where(Participant.list_id == participant_list.id)
                .order_by(Participant.created_at)
            )
        ).scalars().all()

        for participant in participants:
            session.add(
                CollectionParticipant(
                    collection_id=item.id,
                    participant_id=participant.id,
                    payment_reference=f"ZM-{uuid.uuid4().hex[:10].upper()}",
                    public_token=secrets.token_urlsafe(24),
                    status="open",
                )
            )

        if payload.communication_mode == "internal":
            session.add(
                ScheduledJob(
                    organization_id=stored_org.id,
                    job_type="send_collection",
                    payload=json.dumps({"collection_id": str(item.id)}),
                    scheduled_at=send_at,
                )
            )
        await session.flush()
        return _summary(item, len(participants), 0, stored_org)


@router.get("/{collection_id}", response_model=CollectionDetail)
async def get_collection(
    collection_id: UUID,
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> CollectionDetail:
    item = await _owned_collection(session, organization, collection_id)
    rows = (
        await session.execute(
            select(CollectionParticipant, Participant)
            .join(Participant, Participant.id == CollectionParticipant.participant_id)
            .where(CollectionParticipant.collection_id == item.id)
            .order_by(Participant.name, CollectionParticipant.created_at)
        )
    ).all()

    payment_methods: dict[UUID, str] = {}
    delivery_statuses: dict[UUID, str] = {}
    communication_counts: dict[UUID, int] = {}
    cp_ids = [cp.id for cp, _participant in rows]
    if cp_ids:
        payment_rows = (
            await session.execute(
                select(Payment.collection_participant_id, Payment.method, Payment.booked_at)
                .where(Payment.collection_participant_id.in_(cp_ids))
                .order_by(Payment.booked_at.desc())
            )
        ).all()
        for cp_id, method, _booked_at in payment_rows:
            payment_methods.setdefault(cp_id, method)

        message_rows = (
            await session.execute(
                select(
                    CommunicationMessage.collection_participant_id,
                    CommunicationMessage.status,
                    CommunicationMessage.created_at,
                )
                .where(
                    CommunicationMessage.collection_participant_id.in_(cp_ids),
                    CommunicationMessage.status != "draft",
                )
                .order_by(CommunicationMessage.created_at.desc())
            )
        ).all()
        for cp_id, message_status, _created_at in message_rows:
            delivery_statuses.setdefault(cp_id, message_status)
        count_rows = (
            await session.execute(
                select(
                    CommunicationMessage.collection_participant_id,
                    func.count(CommunicationMessage.id),
                )
                .where(
                    CommunicationMessage.collection_participant_id.in_(cp_ids),
                    CommunicationMessage.status != "draft",
                )
                .group_by(CommunicationMessage.collection_participant_id)
            )
        ).all()
        communication_counts = {cp_id: int(count) for cp_id, count in count_rows}

    _include_link, include_qr = _effective_message_options(item, organization)
    participants = [
        _participant_read(
            cp=cp,
            participant=participant,
            payment_method=payment_methods.get(cp.id),
            delivery_status=delivery_statuses.get(cp.id),
            communication_count=communication_counts.get(cp.id, 0),
            payment_qr_url=_payment_qr_url_if_available(
                organization=organization, collection=item, cp=cp, enabled=include_qr
            ),
        )
        for cp, participant in rows
    ]
    paid_count = sum(1 for participant in participants if participant.status == "paid")
    base = _summary(item, len(participants), paid_count, organization)
    return CollectionDetail(**base.model_dump(), participants=participants)


@router.patch("/{collection_id}", response_model=CollectionRead)
async def update_collection(
    collection_id: UUID,
    payload: CollectionUpdate,
    organization: Organization = Depends(get_organization),
) -> CollectionRead:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        item = await _owned_collection(session, stored_org, collection_id, for_update=True)
        if "name" in payload.model_fields_set:
            item.name = await unique_collection_name(
                session, stored_org, payload.name, exclude_id=item.id
            )
        if "due_at" in payload.model_fields_set:
            item.due_at = payload.due_at
        if "include_payment_link" in payload.model_fields_set:
            item.message_include_payment_link = payload.include_payment_link
        if "include_payment_qr" in payload.model_fields_set:
            item.message_include_payment_qr = payload.include_payment_qr
        include_link, include_qr = _effective_message_options(item, stored_org)
        _validate_message_options(include_link, include_qr)
        total = await session.scalar(
            select(func.count()).where(CollectionParticipant.collection_id == item.id)
        )
        paid = await session.scalar(
            select(func.count()).where(
                CollectionParticipant.collection_id == item.id,
                CollectionParticipant.status == "paid",
            )
        )
        return _summary(item, total or 0, paid or 0, stored_org)


@router.post("/{collection_id}/send", response_model=QueueActionResult, status_code=202)
async def queue_collection_send(
    collection_id: UUID,
    organization: Organization = Depends(get_organization),
) -> QueueActionResult:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        _require_bank_account(stored_org)
        item = await _owned_collection(
            session, stored_org, collection_id, for_update=True
        )
        if item.communication_mode != "internal":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="External communication is sent manually")
        unsent = await session.scalar(
            select(func.count()).where(
                CollectionParticipant.collection_id == item.id,
                CollectionParticipant.initial_sent_at.is_(None),
            )
        )
        if not unsent:
            return QueueActionResult(queued=0)
        job_payload = json.dumps({"collection_id": str(item.id)})
        if await _active_job_exists(session, job_type="send_collection", payload=job_payload):
            return QueueActionResult(queued=0)
        session.add(
            ScheduledJob(
                organization_id=stored_org.id,
                job_type="send_collection",
                payload=job_payload,
                scheduled_at=datetime.now(UTC),
            )
        )
        return QueueActionResult(queued=int(unsent))


@router.post("/{collection_id}/remind", response_model=QueueActionResult, status_code=202)
async def queue_collection_reminder(
    collection_id: UUID,
    organization: Organization = Depends(get_organization),
) -> QueueActionResult:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        _require_bank_account(stored_org)
        item = await _owned_collection(
            session, stored_org, collection_id, for_update=True
        )
        if item.communication_mode != "internal":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="External communication is sent manually")
        open_count = await session.scalar(
            select(func.count()).where(
                CollectionParticipant.collection_id == item.id,
                CollectionParticipant.status == "open",
                CollectionParticipant.initial_sent_at.is_not(None),
            )
        )
        if not open_count:
            return QueueActionResult(queued=0)
        job_payload = json.dumps({"collection_id": str(item.id), "automatic": False})
        if await _active_job_exists(session, job_type="send_reminders", payload=job_payload):
            return QueueActionResult(queued=0)
        session.add(
            ScheduledJob(
                organization_id=stored_org.id,
                job_type="send_reminders",
                payload=job_payload,
                scheduled_at=datetime.now(UTC),
            )
        )
        return QueueActionResult(queued=int(open_count))


@router.put(
    "/{collection_id}/participants/{collection_participant_id}/payment-status",
    response_model=CollectionParticipantRead,
)
async def set_manual_payment_status(
    collection_id: UUID,
    collection_participant_id: UUID,
    payload: PaymentStatusUpdate,
    organization: Organization = Depends(get_organization),
) -> CollectionParticipantRead:
    now = datetime.now(UTC)
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        collection = await _owned_collection(session, stored_org, collection_id)
        cp = await session.get(
            CollectionParticipant, collection_participant_id, with_for_update=True
        )
        if cp is None or cp.collection_id != collection.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Collection participant not found"
            )
        participant = await session.get(Participant, cp.participant_id)
        assert participant is not None

        if payload.paid and cp.status != "paid":
            cp.status = "paid"
            cp.paid_at = now
            existing_manual = await session.scalar(
                select(Payment.id).where(
                    Payment.collection_participant_id == cp.id,
                    Payment.method == "manual",
                )
            )
            if existing_manual is None:
                session.add(
                    Payment(
                        collection_participant_id=cp.id,
                        amount=collection.amount,
                        currency=collection.currency,
                        method="manual",
                        booked_at=now,
                        details="Marked as paid manually",
                    )
                )
        elif not payload.paid and cp.status == "paid":
            non_manual_count = await session.scalar(
                select(func.count()).where(
                    Payment.collection_participant_id == cp.id,
                    Payment.method != "manual",
                )
            )
            if non_manual_count:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A synchronized/imported payment cannot be cleared manually",
                )
            await session.execute(
                delete(Payment).where(
                    Payment.collection_participant_id == cp.id,
                    Payment.method == "manual",
                )
            )
            cp.status = "open"
            cp.paid_at = None

        latest_delivery = await session.scalar(
            select(CommunicationMessage.status)
            .where(
                CommunicationMessage.collection_participant_id == cp.id,
                CommunicationMessage.status != "draft",
            )
            .order_by(CommunicationMessage.created_at.desc())
            .limit(1)
        )
        payment_method = await session.scalar(
            select(Payment.method)
            .where(Payment.collection_participant_id == cp.id)
            .order_by(Payment.booked_at.desc(), Payment.created_at.desc())
            .limit(1)
        )
        _include_link, include_qr = _effective_message_options(collection, stored_org)
        return _participant_read(
            cp=cp,
            participant=participant,
            payment_method=payment_method if cp.status == "paid" else None,
            delivery_status=latest_delivery,
            payment_qr_url=_payment_qr_url_if_available(
                organization=stored_org, collection=collection, cp=cp, enabled=include_qr
            ),
        )
