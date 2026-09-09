from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.deps import get_organization
from app.db.session import SessionLocal
from app.models.entities import (
    Collection,
    CollectionParticipant,
    MessageTemplate,
    Organization,
    Participant,
    ParticipantList,
)
from app.models.participant_preferences import ParticipantPreference
from app.services import translation
from app.services.collection_message_overrides import (
    deserialize_collection_message_overrides,
    serialize_collection_message_overrides,
)
from app.services.templates import normalize_language, normalize_translations, validate_template_body

router = APIRouter(prefix="/collections", tags=["collections"])


class CollectionMessageTranslationsRead(BaseModel):
    translations: dict[str, str] = Field(default_factory=dict)
    required_languages: list[str] = Field(default_factory=list)
    translation_configured: bool = False
    has_override: bool = False


class CollectionMessageTranslationUpdate(BaseModel):
    language: str = Field(max_length=10)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        normalized = normalize_language(value, fallback="")
        if not normalized:
            raise ValueError(f"Unsupported language: {value}")
        return normalized

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        body = value.strip()
        validate_template_body(body)
        return body


class CollectionMessageTranslateRequest(CollectionMessageTranslationUpdate):
    pass


class CollectionMessagePreviewRequest(CollectionMessageTranslationUpdate):
    participant_list_id: UUID


async def _owned_collection(session, organization: Organization, collection_id: UUID) -> Collection:
    item = await session.get(Collection, collection_id, with_for_update=True)
    if item is None or item.organization_id != organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    return item


async def _required_languages(session, collection: Collection, organization: Organization) -> list[str]:
    languages = {normalize_language(organization.locale)}
    participant_ids = list(
        (
            await session.execute(
                select(CollectionParticipant.participant_id).where(
                    CollectionParticipant.collection_id == collection.id
                )
            )
        ).scalars()
    )
    if participant_ids:
        locales = (
            await session.execute(
                select(ParticipantPreference.locale).where(
                    ParticipantPreference.participant_id.in_(participant_ids)
                )
            )
        ).scalars().all()
        languages.update(normalize_language(locale) for locale in locales if locale)
    return sorted(languages)


async def _required_languages_for_list(
    session, participant_list: ParticipantList, organization: Organization
) -> list[str]:
    languages = {normalize_language(organization.locale)}
    participant_ids = list(
        (
            await session.execute(
                select(Participant.id).where(Participant.list_id == participant_list.id)
            )
        ).scalars()
    )
    if participant_ids:
        locales = (
            await session.execute(
                select(ParticipantPreference.locale).where(
                    ParticipantPreference.participant_id.in_(participant_ids)
                )
            )
        ).scalars().all()
        languages.update(normalize_language(locale) for locale in locales if locale)
    return sorted(languages)


async def _effective_translations(
    session, collection: Collection, organization: Organization
) -> tuple[dict[str, str], bool]:
    overrides = deserialize_collection_message_overrides(collection.message_overrides_json)
    if overrides:
        return overrides, True
    if collection.message_template_id is not None:
        template = await session.get(MessageTemplate, collection.message_template_id)
        if template is not None and template.organization_id == organization.id:
            return normalize_translations(template.translations_json), False
    return {}, False


async def _read(
    session, collection: Collection, organization: Organization
) -> CollectionMessageTranslationsRead:
    translations, has_override = await _effective_translations(session, collection, organization)
    return CollectionMessageTranslationsRead(
        translations=translations,
        required_languages=await _required_languages(session, collection, organization),
        translation_configured=translation.configured(),
        has_override=has_override,
    )


@router.post(
    "/message-translations/preview",
    response_model=CollectionMessageTranslationsRead,
)
async def preview_collection_message_translations(
    payload: CollectionMessagePreviewRequest,
    organization: Organization = Depends(get_organization),
) -> CollectionMessageTranslationsRead:
    if not translation.configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Automatic translation is not configured",
        )
    async with SessionLocal() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        participant_list = await session.get(ParticipantList, payload.participant_list_id)
        if participant_list is None or participant_list.organization_id != stored_org.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant list not found")
        targets = await _required_languages_for_list(session, participant_list, stored_org)

    try:
        generated = await translation.translate_other_languages(
            payload.body,
            source_language=payload.language,
            target_languages=targets,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Automatic translation failed",
        ) from exc
    return CollectionMessageTranslationsRead(
        translations=generated,
        required_languages=targets,
        translation_configured=True,
        has_override=True,
    )


@router.get(
    "/{collection_id}/message-translations",
    response_model=CollectionMessageTranslationsRead,
)
async def get_collection_message_translations(
    collection_id: UUID,
    organization: Organization = Depends(get_organization),
) -> CollectionMessageTranslationsRead:
    async with SessionLocal() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        collection = await _owned_collection(session, stored_org, collection_id)
        return await _read(session, collection, stored_org)


@router.put(
    "/{collection_id}/message-translations",
    response_model=CollectionMessageTranslationsRead,
)
async def update_collection_message_translation(
    collection_id: UUID,
    payload: CollectionMessageTranslationUpdate,
    organization: Organization = Depends(get_organization),
) -> CollectionMessageTranslationsRead:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        collection = await _owned_collection(session, stored_org, collection_id)
        translations, _has_override = await _effective_translations(session, collection, stored_org)
        translations[payload.language] = payload.body
        collection.message_overrides_json = serialize_collection_message_overrides(translations)
        await session.flush()
        return await _read(session, collection, stored_org)


@router.post(
    "/{collection_id}/message-translations/translate-other-languages",
    response_model=CollectionMessageTranslationsRead,
)
async def translate_collection_message_languages(
    collection_id: UUID,
    payload: CollectionMessageTranslateRequest,
    organization: Organization = Depends(get_organization),
) -> CollectionMessageTranslationsRead:
    if not translation.configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Automatic translation is not configured",
        )

    async with SessionLocal() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        collection = await _owned_collection(session, stored_org, collection_id)
        targets = await _required_languages(session, collection, stored_org)

    try:
        generated = await translation.translate_other_languages(
            payload.body,
            source_language=payload.language,
            target_languages=targets,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Automatic translation failed",
        ) from exc

    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        collection = await _owned_collection(session, stored_org, collection_id)
        current, _has_override = await _effective_translations(session, collection, stored_org)
        current.update(generated)
        collection.message_overrides_json = serialize_collection_message_overrides(current)
        await session.flush()
        return await _read(session, collection, stored_org)
