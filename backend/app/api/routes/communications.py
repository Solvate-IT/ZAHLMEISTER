import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import get_organization, get_session
from app.db.session import SessionLocal
from app.models.entities import (
    Collection,
    CollectionParticipant,
    CommunicationMessage,
    Organization,
    Participant,
    ScheduledJob,
)
from app.schemas.communications import (
    ChannelFeedbackRequest,
    CommunicationRead,
    ExternalDraftRead,
    ExternalDraftRequest,
    ExternalOpenedRequest,
    ExternalResultRequest,
    InternalMessageRequest,
    QueueMessageResult,
)
from app.services.channel_strategy import (
    channel_addresses,
    load_channel_runtimes,
    set_channel_knowledge,
)
from app.services.communications import external_launch_uri, recipient_for_channel
from app.services.message_renderer import render_collection_message

router = APIRouter(tags=["communications"])


async def _owned_context(
    session,
    organization: Organization,
    collection_id: UUID,
    cp_id: UUID,
    *,
    for_update: bool = False,
):
    stmt = (
        select(CollectionParticipant, Collection, Participant)
        .join(Collection, Collection.id == CollectionParticipant.collection_id)
        .join(Participant, Participant.id == CollectionParticipant.participant_id)
        .where(
            Collection.id == collection_id,
            Collection.organization_id == organization.id,
            CollectionParticipant.id == cp_id,
        )
    )
    if for_update:
        stmt = stmt.with_for_update(of=CollectionParticipant)
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    return row


def _to_read(message: CommunicationMessage) -> CommunicationRead:
    return CommunicationRead(
        id=message.id,
        kind=message.kind,
        channel=message.channel,
        delivery_mode=message.delivery_mode,
        direction=message.direction,
        sender=message.sender,
        recipient=message.recipient,
        subject=message.subject,
        body=message.body,
        status=message.status,
        provider=message.provider,
        sent_at=message.sent_at,
        received_at=message.received_at,
        created_at=message.created_at,
        error=message.error,
    )


@router.get(
    "/collections/{collection_id}/participants/{cp_id}/communications",
    response_model=list[CommunicationRead],
)
async def list_communications(
    collection_id: UUID,
    cp_id: UUID,
    organization: Organization = Depends(get_organization),
    session=Depends(get_session),
) -> list[CommunicationRead]:
    await _owned_context(session, organization, collection_id, cp_id)
    messages = (
        await session.execute(
            select(CommunicationMessage)
            .where(
                CommunicationMessage.collection_participant_id == cp_id,
                CommunicationMessage.status != "draft",
            )
            .order_by(CommunicationMessage.created_at.desc())
        )
    ).scalars().all()
    return [_to_read(message) for message in messages]


@router.post(
    "/collections/{collection_id}/participants/{cp_id}/communications/external-draft",
    response_model=ExternalDraftRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_external_draft(
    collection_id: UUID,
    cp_id: UUID,
    payload: ExternalDraftRequest,
    organization: Organization = Depends(get_organization),
) -> ExternalDraftRead:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        cp, collection, participant = await _owned_context(
            session, stored_org, collection_id, cp_id, for_update=True
        )
        runtimes = await load_channel_runtimes(session, stored_org.id)
        runtime = runtimes.get(payload.channel)
        if runtime is None or runtime.mode != "external":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"External {payload.channel} is not enabled",
            )
        recipient = recipient_for_channel(
            payload.channel,
            email=participant.email,
            phone=participant.phone,
            channel_addresses=channel_addresses(participant),
        )
        if not recipient:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No recipient available for {payload.channel}",
            )
        content = await render_collection_message(
            session,
            collection=collection,
            collection_participant=cp,
            participant=participant,
            organization=stored_org,
        )
        message = CommunicationMessage(
            organization_id=stored_org.id,
            collection_id=collection.id,
            collection_participant_id=cp.id,
            kind=payload.kind,
            channel=payload.channel,
            delivery_mode="external",
            direction="outgoing",
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            status="draft",
            metadata_json=content.metadata_json(),
        )
        session.add(message)
        await session.flush()
        launch_uri, recipient_selection_required = external_launch_uri(
            payload.channel, recipient, content.subject, content.text
        )
        return ExternalDraftRead(
            message_id=message.id,
            channel=payload.channel,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            launch_uri=launch_uri,
            recipient_selection_required=recipient_selection_required,
            payment_qr_url=content.payment_qr_url,
            payment_qr_filename=(
                f"zahlmeister-{cp.payment_reference}-qr.png" if content.payment_qr_url else None
            ),
        )


@router.post(
    "/collections/{collection_id}/participants/{cp_id}/communications/external-opened",
    response_model=CommunicationRead,
)
async def mark_external_opened(
    collection_id: UUID,
    cp_id: UUID,
    payload: ExternalOpenedRequest,
    organization: Organization = Depends(get_organization),
) -> CommunicationRead:
    async with SessionLocal.begin() as session:
        await _owned_context(session, organization, collection_id, cp_id)
        message = await session.get(CommunicationMessage, payload.message_id, with_for_update=True)
        if (
            message is None
            or message.organization_id != organization.id
            or message.collection_participant_id != cp_id
            or message.delivery_mode != "external"
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
        message.status = "external_opened"
        message.error = None
        await session.flush()
        await session.refresh(message)
        return _to_read(message)


@router.post(
    "/collections/{collection_id}/participants/{cp_id}/communications/external-result",
    response_model=CommunicationRead,
)
async def confirm_external_result(
    collection_id: UUID,
    cp_id: UUID,
    payload: ExternalResultRequest,
    organization: Organization = Depends(get_organization),
) -> CommunicationRead:
    now = datetime.now(UTC)
    async with SessionLocal.begin() as session:
        cp, _collection, participant = await _owned_context(
            session, organization, collection_id, cp_id, for_update=True
        )
        message = await session.get(CommunicationMessage, payload.message_id, with_for_update=True)
        if (
            message is None
            or message.organization_id != organization.id
            or message.collection_participant_id != cp.id
            or message.delivery_mode != "external"
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

        if payload.result == "sent":
            message.status = "sent"
            message.sent_at = now
            message.error = None
            if message.kind == "initial" and cp.initial_sent_at is None:
                cp.initial_sent_at = now
            elif message.kind == "reminder":
                cp.last_reminder_at = now
                cp.reminder_count += 1
            if message.channel == "whatsapp":
                await set_channel_knowledge(
                    session,
                    participant.id,
                    "whatsapp",
                    availability="available",
                )
        elif payload.result == "unavailable":
            message.status = "failed"
            message.error = "Recipient reported unavailable for this channel"
            await set_channel_knowledge(
                session,
                participant.id,
                message.channel,
                availability="unavailable",
                failure_reason="Recipient reported unavailable for this channel",
            )
        else:
            message.status = "skipped"
            message.error = None
        await session.flush()
        await session.refresh(message)
        return _to_read(message)


@router.post(
    "/collections/{collection_id}/participants/{cp_id}/channels/{channel}/feedback",
    response_model=CommunicationRead | None,
)
async def set_channel_feedback(
    collection_id: UUID,
    cp_id: UUID,
    channel: str,
    payload: ChannelFeedbackRequest,
    organization: Organization = Depends(get_organization),
):
    async with SessionLocal.begin() as session:
        _cp, _collection, participant = await _owned_context(
            session, organization, collection_id, cp_id, for_update=True
        )
        try:
            await set_channel_knowledge(
                session,
                participant.id,
                channel,
                availability=payload.availability,
                failure_reason=payload.failure_reason,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
    return None


@router.post(
    "/collections/{collection_id}/participants/{cp_id}/communications/internal",
    response_model=QueueMessageResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_internal_message(
    collection_id: UUID,
    cp_id: UUID,
    payload: InternalMessageRequest,
    organization: Organization = Depends(get_organization),
) -> QueueMessageResult:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        cp, collection, participant = await _owned_context(
            session, stored_org, collection_id, cp_id, for_update=True
        )
        existing = await session.scalar(
            select(CommunicationMessage)
            .where(
                CommunicationMessage.collection_participant_id == cp.id,
                CommunicationMessage.kind == payload.kind,
                CommunicationMessage.channel == payload.channel,
                CommunicationMessage.delivery_mode == "internal",
                CommunicationMessage.direction == "outgoing",
                CommunicationMessage.status == "queued",
            )
            .order_by(CommunicationMessage.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            return QueueMessageResult(message_id=existing.id, status="queued")

        runtimes = await load_channel_runtimes(session, stored_org.id)
        runtime = runtimes.get(payload.channel)
        if runtime is None or runtime.mode != "internal" or not runtime.configured:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Internal {payload.channel} is not configured",
            )
        recipient = recipient_for_channel(
            payload.channel,
            email=participant.email,
            phone=participant.phone,
            channel_addresses=channel_addresses(participant),
        )
        if not recipient:
            message = CommunicationMessage(
                organization_id=stored_org.id,
                collection_id=collection.id,
                collection_participant_id=cp.id,
                kind=payload.kind,
                channel=payload.channel,
                delivery_mode="internal",
                direction="outgoing",
                status="failed",
                error=f"No recipient available for {payload.channel}",
            )
            session.add(message)
            await session.flush()
            return QueueMessageResult(message_id=message.id, status="failed")

        content = await render_collection_message(
            session,
            collection=collection,
            collection_participant=cp,
            participant=participant,
            organization=stored_org,
        )
        message = CommunicationMessage(
            organization_id=stored_org.id,
            collection_id=collection.id,
            collection_participant_id=cp.id,
            kind=payload.kind,
            channel=payload.channel,
            delivery_mode="internal",
            direction="outgoing",
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            status="queued",
            provider=runtime.provider,
            metadata_json=content.metadata_json(),
        )
        session.add(message)
        await session.flush()
        session.add(
            ScheduledJob(
                organization_id=stored_org.id,
                job_type="send_message",
                payload=json.dumps({"message_id": str(message.id)}),
                scheduled_at=datetime.now(UTC),
            )
        )
        return QueueMessageResult(message_id=message.id, status="queued")
