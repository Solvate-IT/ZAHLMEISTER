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
    get_channel_order,
    load_channel_runtimes,
    load_participant_channel_settings,
    resolve_channel,
)
from app.services.message_renderer import render_collection_message


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
        return cp.initial_sent_at is None
    if kind == "reminder":
        return cp.status == "open" and cp.initial_sent_at is not None
    return False


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
    runtimes = await load_channel_runtimes(session, organization.id)
    order = await get_channel_order(session, organization.id)

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
        route = resolve_channel(
            participant,
            order=order,
            runtimes=runtimes,
            overrides=overrides.get(participant.id),
            external_channels=external_channels,
        )
        if route is None:
            outcome.unreachable.append(cp.id)
            continue
        if route.mode == "external":
            if include_external:
                outcome.external.append(
                    ExternalDispatch(
                        collection_participant_id=cp.id,
                        participant_id=participant.id,
                        name=participant.name,
                        channel=route.channel,
                    )
                )
            continue

        content = await render_collection_message(
            session,
            collection=collection,
            collection_participant=cp,
            participant=participant,
            organization=organization,
        )
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
    order = await get_channel_order(session, organization.id)
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
