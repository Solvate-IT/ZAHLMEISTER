from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.participant_preferences import ParticipantPreference
from app.services.templates import SUPPORTED_LANGUAGES


def normalize_participant_locale(value: str | None) -> str | None:
    if value is None:
        return None
    language = value.strip().lower().split("-", 1)[0].split("_", 1)[0]
    if not language:
        return None
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {value}")
    return language


async def load_participant_locales(
    session: AsyncSession, participant_ids: list[UUID]
) -> dict[UUID, str]:
    if not participant_ids:
        return {}
    rows = (
        await session.execute(
            select(ParticipantPreference.participant_id, ParticipantPreference.locale).where(
                ParticipantPreference.participant_id.in_(participant_ids)
            )
        )
    ).all()
    return {participant_id: locale for participant_id, locale in rows}


async def get_participant_locale(session: AsyncSession, participant_id: UUID) -> str | None:
    return await session.scalar(
        select(ParticipantPreference.locale).where(
            ParticipantPreference.participant_id == participant_id
        )
    )


async def save_participant_locale(
    session: AsyncSession, participant_id: UUID, locale: str | None
) -> str | None:
    normalized = normalize_participant_locale(locale)
    existing = await session.get(ParticipantPreference, participant_id, with_for_update=True)
    if normalized is None:
        if existing is not None:
            await session.delete(existing)
        return None
    if existing is None:
        session.add(ParticipantPreference(participant_id=participant_id, locale=normalized))
    else:
        existing.locale = normalized
    return normalized
