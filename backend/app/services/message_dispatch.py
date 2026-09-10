from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Collection,
    CollectionParticipant,
    CommunicationMessage,
    Organization,
    Participant,
    ScheduledJob,
)
from app.services.channel_strategy import (
    SUPPORTED_CHANNELS,
    get_channel_order,
    load_channel_runtimes,
    load_participant_channel_settings,
    resolve_channel,
)
from app.services.message_renderer import render_collection_message
from app.services.participant_preferences import load_participant_locales


@dataclass(frozen=True)
class ExternalDispatch:
    collection_participant_id: UUID
    participant_id: UUID
    name: str
    channel: str


@dataclass
class DispatchOutcome:
    queued_internal: int = 0
    external: list[ExternalDispatch] = field(default_factory=list)
    unreachable: list[UUID] = field(default_factory=list)


def _eligible(cp: CollectionParticipant, kind: str) -> bool:
    if kind == "initial":
        return cp.status == "open" and cp.initial_sent_at is None
    if kind == "reminder":
        return cp.status == "open" and cp.initial_sent_at is not None
    return False


async def _collection_channel_order(
    session: AsyncSession,
    *,
    collection: Collection,
    organization_id: UUID,
) -> list[str]:
    override = str(collection.communication_channel or "auto").strip().lower()
    if override in SUPPORTED_CHANNELS:
        return [override]
    return await get_channel_order(session, organization_id)


def _external_outcome(
    outcome: DispatchOutcome,
    *,
    cp: CollectionParticipant,
    participant: Participant,
    channel: str,
    include_external: bool,
) -> None:
    if include_external:
        outcome.external.append(
            ExternalDispatch(
                collection_participant_id=cp.id,
                participant_id=participant.id,
                name=participant.name,
                channel=channel,
            )
        )


async def queue_collection_messages(
    session: AsyncSession,
    *,
    collection: Collection,
    organization: Organization,
    kind: str,
    external_channels: set[str] | None = None,
    collection_participant_ids: set[UUID] | None = None,
    include_external: bool = True,
) -> DispatchOutcome:
    """Resolve the configured channel strategy once per participant and queue internal sends."""
    if kind not in {"initial", "reminder"}:
        raise ValueError("Unsupported dispatch kind")

    stmt = (
        select(CollectionParticipant, Participant)
        .join(Participant, Participant.id == CollectionParticipant.participant_id)
        .where(CollectionParticipant.collection_id == collection.id)
        .order_by(CollectionParticipant.created_at)
        .with_for_update(of=CollectionParticipant)
    )
    if collection_participant_ids is not None:
        if not collection_participant_ids:
            return DispatchOutcome()
        stmt = stmt.where(CollectionParticipant.id.in_(collection_participant_ids))
    rows = (await session.execute(stmt)).all()
    eligible_rows = [(cp, participant) for cp, participant in rows if _eligible(cp, kind)]
    if not eligible_rows:
        return DispatchOutcome()

    participant_ids = [participant.id for _cp, participant in eligible_rows]
    cp_ids = [cp.id for cp, _participant in eligible_rows]
    overrides = await load_participant_channel_settings(session, participant_ids)
    participant_locales = await load_participant_locales(session, participant_ids)
    runtimes = await load_channel_runtimes(session, organization.id)
    order = await _collection_channel_order(
        session, collection=collection, organization_id=organization.id
    )

    # Only an outstanding queue item prevents another dispatch. Previously sent reminders
    # must not block later reminder rounds for the same participant.
    queued_rows = (
        await session.execute(
            select(CommunicationMessage.collection_participant_id).where(
                CommunicationMessage.collection_participant_id.in_(cp_ids),
                CommunicationMessage.kind == kind,
                CommunicationMessage.direction == "outgoing",
                CommunicationMessage.status == "queued",
            )
        )
    ).scalars().all()
    already_queued = set(queued_rows)

    outcome = DispatchOutcome()
    now = datetime.now(UTC)
    for cp, participant in eligible_rows:
        if cp.id in already_queued:
            continue
        participant_overrides = overrides.get(participant.id)
        route = resolve_channel(
            participant,
            order=order,
            runtimes=runtimes,
            overrides=participant_overrides,
            external_channels=external_channels,
        )
        if route is None:
            outcome.unreachable.append(cp.id)
            continue
        if route.mode == "external":
            _external_outcome(
                outcome,
                cp=cp,
                participant=participant,
                channel=route.channel,
                include_external=include_external,
            )
            continue

        content = await render_collection_message(
            session,
            collection=collection,
            collection_participant=cp,
            participant=participant,
            organization=organization,
            participant_locale=participant_locales.get(participant.id),
        )

        # Business-initiated WhatsApp traffic must use a Meta-approved template. A
        # custom Zahlmeister message cannot be silently sent under the protected
        # payment-request template, so continue with the next configured channel.
        if (
            route.channel == "whatsapp"
            and route.provider == "infobip"
            and content.whatsapp_template_values is None
        ):
            route = resolve_channel(
                participant,
                order=[candidate for candidate in order if candidate != "whatsapp"],
                runtimes=runtimes,
                overrides=participant_overrides,
                external_channels=external_channels,
            )
            if route is None:
                outcome.unreachable.append(cp.id)
                continue
            if route.mode == "external":
                _external_outcome(
                    outcome,
                    cp=cp,
                    participant=participant,
                    channel=route.channel,
                    include_external=include_external,
                )
                continue

        provider = route.provider
        if (
            route.channel == "email"
            and route.provider == "smtp_imap"
            and not str(route.config.get("smtp_host") or "").strip()
            and not str(route.config.get("from_address") or "").strip()
        ):
            provider = "zahlmeister_email"
        message = CommunicationMessage(
            organization_id=organization.id,
            collection_id=collection.id,
            collection_participant_id=cp.id,
            kind=kind,
            channel=route.channel,
            delivery_mode="internal",
            direction="outgoing",
            recipient=route.recipient,
            subject=content.subject,
            body=content.text,
            status="queued",
            provider=provider,
            metadata_json=content.metadata_json(),
        )
        session.add(message)
        await session.flush()
        session.add(
            ScheduledJob(
                organization_id=organization.id,
                job_type="send_message",
                payload=json.dumps({"message_id": str(message.id)}),
                scheduled_at=now,
            )
        )
        outcome.queued_internal += 1

    return outcome


async def queue_failed_channel_fallback(
    session: AsyncSession,
    *,
    failed_message: CommunicationMessage,
) -> DispatchOutcome:
    """Queue the next internal route after a confirmed permanent channel failure.

    External fallbacks are deliberately not opened from a background webhook. Leaving the
    participant eligible means the next interactive dispatch presents only that participant
    in the manual assistant.
    """
    if failed_message.kind not in {"initial", "reminder"}:
        return DispatchOutcome()

    cp = await session.get(
        CollectionParticipant,
        failed_message.collection_participant_id,
        with_for_update=True,
    )
    if cp is None or cp.status != "open":
        return DispatchOutcome()

    # Provider webhooks may be delivered more than once or out of order. If another
    # attempt for the same logical message has already succeeded, never reopen dispatch.
    later_success = await session.scalar(
        select(CommunicationMessage.id)
        .where(
            CommunicationMessage.collection_participant_id == cp.id,
            CommunicationMessage.kind == failed_message.kind,
            CommunicationMessage.direction == "outgoing",
            CommunicationMessage.id != failed_message.id,
            CommunicationMessage.created_at >= failed_message.created_at,
            CommunicationMessage.status.in_(["sent", "delivered", "read"]),
        )
        .limit(1)
    )
    if later_success is not None:
        return DispatchOutcome()

    if failed_message.kind == "initial":
        # Internal sends mark initial_sent_at when the provider accepts the request. A
        # confirmed permanent failure must reopen the participant for the next route.
        cp.initial_sent_at = None

    collection = await session.get(Collection, failed_message.collection_id)
    organization = await session.get(Organization, failed_message.organization_id)
    if collection is None or organization is None:
        return DispatchOutcome()

    return await queue_collection_messages(
        session,
        collection=collection,
        organization=organization,
        kind=failed_message.kind,
        collection_participant_ids={cp.id},
        include_external=False,
    )


async def all_routes_internal(
    session: AsyncSession,
    *,
    collection: Collection,
    organization: Organization,
) -> bool:
    rows = (
        await session.execute(
            select(CollectionParticipant, Participant)
            .join(Participant, Participant.id == CollectionParticipant.participant_id)
            .where(CollectionParticipant.collection_id == collection.id)
        )
    ).all()
    if not rows:
        return True
    overrides = await load_participant_channel_settings(
        session, [participant.id for _cp, participant in rows]
    )
    runtimes = await load_channel_runtimes(session, organization.id)
    order = await _collection_channel_order(
        session, collection=collection, organization_id=organization.id
    )
    for _cp, participant in rows:
        route = resolve_channel(
            participant,
            order=order,
            runtimes=runtimes,
            overrides=overrides.get(participant.id),
        )
        if route is None or route.mode != "internal":
            return False
    return True
