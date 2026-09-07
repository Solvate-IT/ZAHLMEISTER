from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel_strategy import CommunicationPreference, ParticipantChannelSetting
from app.models.entities import CommunicationChannelSetting, CommunicationConnection, Participant
from app.services.channel_config import canonical_internal_provider, internal_channel_configured
from app.services.communications import recipient_for_channel
from app.services.infobip import connection_is_active
from app.services.secrets import decrypt_config

SUPPORTED_CHANNELS = ("email", "whatsapp", "sms", "telegram")
DEFAULT_CHANNEL_ORDER = ("email", "whatsapp", "sms", "telegram")
DEFAULT_CHANNEL_MODES = {
    "email": "internal",
    "whatsapp": "external",
    "sms": "external",
    "telegram": "disabled",
}


@dataclass(frozen=True)
class ChannelRuntime:
    channel: str
    mode: str
    provider: str | None
    connection_id: UUID | None
    sender: str | None
    config: dict
    configured: bool


@dataclass(frozen=True)
class ResolvedChannel:
    channel: str
    mode: str
    recipient: str
    provider: str | None
    connection_id: UUID | None
    sender: str | None
    config: dict
    availability: str


def channel_addresses(participant: Participant) -> dict[str, str]:
    try:
        data = json.loads(participant.channel_addresses_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if value}


def normalize_channel_order(value: object) -> list[str]:
    if not isinstance(value, list):
        return list(DEFAULT_CHANNEL_ORDER)
    result: list[str] = []
    for item in value:
        channel = str(item).strip().lower()
        if channel in SUPPORTED_CHANNELS and channel not in result:
            result.append(channel)
    for channel in DEFAULT_CHANNEL_ORDER:
        if channel not in result:
            result.append(channel)
    return result


def decode_channel_order(raw: str | None) -> list[str]:
    try:
        return normalize_channel_order(json.loads(raw or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return list(DEFAULT_CHANNEL_ORDER)


async def get_channel_order(session: AsyncSession, organization_id: UUID) -> list[str]:
    row = await session.get(CommunicationPreference, organization_id)
    return decode_channel_order(row.channel_order_json if row else None)


async def save_channel_order(
    session: AsyncSession, organization_id: UUID, channels: list[str]
) -> list[str]:
    normalized = normalize_channel_order(channels)
    if set(channels) != set(SUPPORTED_CHANNELS) or len(channels) != len(SUPPORTED_CHANNELS):
        raise ValueError("Channel order must contain each supported channel exactly once")
    row = await session.get(CommunicationPreference, organization_id, with_for_update=True)
    if row is None:
        row = CommunicationPreference(organization_id=organization_id)
        session.add(row)
    row.channel_order_json = json.dumps(normalized, separators=(",", ":"))
    await session.flush()
    return normalized


def _default_setting(channel: str) -> ChannelRuntime:
    mode = DEFAULT_CHANNEL_MODES[channel]
    provider = "zahlmeister_email" if channel == "email" and mode == "internal" else None
    configured = mode == "external" or (
        channel == "email"
        and mode == "internal"
        and internal_channel_configured(channel, provider=provider, config={})
    )
    return ChannelRuntime(
        channel=channel,
        mode=mode,
        provider=provider,
        connection_id=None,
        sender=None,
        config={},
        configured=configured,
    )


async def load_channel_runtimes(
    session: AsyncSession, organization_id: UUID
) -> dict[str, ChannelRuntime]:
    rows = (
        await session.execute(
            select(CommunicationChannelSetting).where(
                CommunicationChannelSetting.organization_id == organization_id,
                CommunicationChannelSetting.channel.in_(SUPPORTED_CHANNELS),
            )
        )
    ).scalars().all()
    connection_ids = {row.connection_id for row in rows if row.connection_id}
    connections: dict[UUID, CommunicationConnection] = {}
    if connection_ids:
        connection_rows = (
            await session.execute(
                select(CommunicationConnection).where(
                    CommunicationConnection.id.in_(connection_ids)
                )
            )
        ).scalars().all()
        connections = {row.id: row for row in connection_rows}

    result = {channel: _default_setting(channel) for channel in SUPPORTED_CHANNELS}
    for row in rows:
        if row.channel not in SUPPORTED_CHANNELS:
            continue
        mode = row.mode if row.mode in {"internal", "external", "disabled"} else "external"
        config = decrypt_config(row.encrypted_config)
        provider = canonical_internal_provider(row.channel, row.provider, config)
        connection = connections.get(row.connection_id) if row.connection_id else None
        if provider == "microsoft365":
            active = bool(connection and connection.status == "connected")
        else:
            active = connection_is_active(connection)
        configured = mode == "external" or (
            mode == "internal"
            and internal_channel_configured(
                row.channel,
                provider=provider,
                config=config,
                connection_active=active,
                sender=row.sender,
            )
        )
        result[row.channel] = ChannelRuntime(
            channel=row.channel,
            mode=mode,
            provider=provider,
            connection_id=row.connection_id,
            sender=row.sender,
            config=config,
            configured=configured,
        )
    return result


async def load_participant_channel_settings(
    session: AsyncSession, participant_ids: list[UUID]
) -> dict[UUID, dict[str, ParticipantChannelSetting]]:
    if not participant_ids:
        return {}
    rows = (
        await session.execute(
            select(ParticipantChannelSetting).where(
                ParticipantChannelSetting.participant_id.in_(participant_ids),
                ParticipantChannelSetting.channel.in_(SUPPORTED_CHANNELS),
            )
        )
    ).scalars().all()
    result: dict[UUID, dict[str, ParticipantChannelSetting]] = {}
    for row in rows:
        result.setdefault(row.participant_id, {})[row.channel] = row
    return result


def default_availability(participant: Participant, channel: str) -> str:
    addresses = channel_addresses(participant)
    recipient = recipient_for_channel(
        channel,
        email=participant.email,
        phone=participant.phone,
        channel_addresses=addresses,
    )
    if not recipient:
        return "unavailable"
    if channel == "whatsapp":
        return "unknown"
    return "available"


def effective_availability(
    participant: Participant,
    channel: str,
    override: ParticipantChannelSetting | None,
) -> str:
    if override and not override.enabled:
        return "unavailable"
    base = default_availability(participant, channel)
    if base == "unavailable":
        return base
    if override and override.availability in {"unknown", "available", "unavailable"}:
        return override.availability
    return base


def resolve_channel(
    participant: Participant,
    *,
    order: list[str],
    runtimes: dict[str, ChannelRuntime],
    overrides: dict[str, ParticipantChannelSetting] | None = None,
    external_channels: set[str] | None = None,
) -> ResolvedChannel | None:
    addresses = channel_addresses(participant)
    overrides = overrides or {}
    for channel in order:
        runtime = runtimes.get(channel)
        if runtime is None or runtime.mode == "disabled":
            continue
        availability = effective_availability(participant, channel, overrides.get(channel))
        if availability == "unavailable":
            continue
        recipient = recipient_for_channel(
            channel,
            email=participant.email,
            phone=participant.phone,
            channel_addresses=addresses,
        )
        if not recipient:
            continue
        if runtime.mode == "internal" and not runtime.configured:
            continue
        if runtime.mode == "external" and external_channels is not None and channel not in external_channels:
            continue
        return ResolvedChannel(
            channel=channel,
            mode=runtime.mode,
            recipient=recipient,
            provider=runtime.provider,
            connection_id=runtime.connection_id,
            sender=runtime.sender,
            config=runtime.config,
            availability=availability,
        )
    return None


async def set_channel_knowledge(
    session: AsyncSession,
    participant_id: UUID,
    channel: str,
    *,
    availability: str | None = None,
    enabled: bool | None = None,
    failure_reason: str | None = None,
) -> ParticipantChannelSetting:
    if channel not in SUPPORTED_CHANNELS:
        raise ValueError("Unsupported communication channel")
    if availability is not None and availability not in {"unknown", "available", "unavailable"}:
        raise ValueError("Invalid channel availability")
    row = await session.scalar(
        select(ParticipantChannelSetting)
        .where(
            ParticipantChannelSetting.participant_id == participant_id,
            ParticipantChannelSetting.channel == channel,
        )
        .with_for_update()
    )
    if row is None:
        row = ParticipantChannelSetting(
            participant_id=participant_id,
            channel=channel,
            availability=availability or "unknown",
            enabled=True if enabled is None else enabled,
        )
        session.add(row)
    else:
        if availability is not None:
            row.availability = availability
        if enabled is not None:
            row.enabled = enabled
    if availability is not None:
        row.last_checked_at = datetime.now(UTC)
        row.last_failure_reason = failure_reason if availability == "unavailable" else None
    await session.flush()
    return row


async def reset_channel_knowledge(
    session: AsyncSession,
    participant_id: UUID,
    channel: str,
) -> None:
    row = await session.scalar(
        select(ParticipantChannelSetting)
        .where(
            ParticipantChannelSetting.participant_id == participant_id,
            ParticipantChannelSetting.channel == channel,
        )
        .with_for_update()
    )
    if row is None:
        return
    row.availability = "unknown"
    row.last_failure_reason = None
    row.last_checked_at = None
