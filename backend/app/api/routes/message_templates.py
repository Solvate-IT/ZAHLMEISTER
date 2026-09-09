from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_organization
from app.db.session import SessionLocal
from app.models.entities import MessageTemplate, Organization
from app.schemas.templates import (
    MessageTemplateCreate,
    MessageTemplateRead,
    MessageTemplateTranslateRequest,
    MessageTemplateTranslationStatus,
    MessageTemplateUpdate,
    TemplateVariableRead,
)
from app.services import translation
from app.services.locks import transaction_lock
from app.services.templates import (
    SUPPORTED_LANGUAGES,
    TEMPLATE_VARIABLES,
    default_template_name,
    default_template_translations,
    normalize_language,
    normalize_translations,
    serialize_translations,
)

router = APIRouter(prefix="/message-templates", tags=["message-templates"])


def _read(item: MessageTemplate) -> MessageTemplateRead:
    return MessageTemplateRead(
        id=item.id,
        name=item.name,
        translations=normalize_translations(item.translations_json),
        is_default=item.is_default,
    )


async def ensure_default_template(session: AsyncSession, organization: Organization) -> MessageTemplate:
    await transaction_lock(session, "message-template", organization.id)
    items = (
        await session.execute(
            select(MessageTemplate)
            .where(
                MessageTemplate.organization_id == organization.id,
                MessageTemplate.is_default.is_(True),
            )
            .order_by(MessageTemplate.created_at)
        )
    ).scalars().all()
    if items:
        for duplicate in items[1:]:
            duplicate.is_default = False
        return items[0]
    item = MessageTemplate(
        organization_id=organization.id,
        name=default_template_name(organization.locale),
        translations_json=serialize_translations(default_template_translations()),
        is_default=True,
    )
    session.add(item)
    await session.flush()
    return item


async def _owned_template(
    session: AsyncSession, organization: Organization, template_id: UUID
) -> MessageTemplate:
    item = await session.get(MessageTemplate, template_id)
    if item is None or item.organization_id != organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return item


async def _unique_name(session: AsyncSession, organization: Organization, requested: str) -> str:
    base = " ".join(requested.split()).strip() or default_template_name(organization.locale)
    existing = set(
        (
            await session.execute(
                select(MessageTemplate.name).where(MessageTemplate.organization_id == organization.id)
            )
        ).scalars()
    )
    if base not in existing:
        return base
    number = 2
    while f"{base} {number}" in existing:
        number += 1
    return f"{base} {number}"


@router.get("/variables", response_model=list[TemplateVariableRead])
async def list_template_variables() -> list[TemplateVariableRead]:
    return [TemplateVariableRead(key=key) for key in TEMPLATE_VARIABLES]


@router.get("/translation-status", response_model=MessageTemplateTranslationStatus)
async def translation_status() -> MessageTemplateTranslationStatus:
    return MessageTemplateTranslationStatus(
        configured=translation.configured(),
        supported_languages=list(SUPPORTED_LANGUAGES),
    )


@router.get("", response_model=list[MessageTemplateRead])
async def list_message_templates(
    organization: Organization = Depends(get_organization),
) -> list[MessageTemplateRead]:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        await ensure_default_template(session, stored_org)
        items = (
            await session.execute(
                select(MessageTemplate)
                .where(MessageTemplate.organization_id == stored_org.id)
                .order_by(MessageTemplate.is_default.desc(), MessageTemplate.name)
            )
        ).scalars().all()
        return [_read(item) for item in items]


@router.post("", response_model=MessageTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_message_template(
    payload: MessageTemplateCreate,
    organization: Organization = Depends(get_organization),
) -> MessageTemplateRead:
    translations: dict[str, str] = {}
    if payload.body:
        source_language = payload.source_language
        if payload.auto_translate:
            if not translation.configured():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Automatic translation is not configured",
                )
            try:
                source_language = source_language or await translation.detect_language(payload.body)
                translations[source_language] = payload.body
                translations = await translation.translate_missing(
                    payload.body,
                    source_language=source_language,
                    existing=translations,
                )
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Automatic translation failed",
                ) from exc
        else:
            source_language = source_language or normalize_language(organization.locale)
            translations[source_language] = payload.body

    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        await ensure_default_template(session, stored_org)
        item = MessageTemplate(
            organization_id=stored_org.id,
            name=await _unique_name(session, stored_org, payload.name),
            translations_json=serialize_translations(translations),
            is_default=False,
        )
        session.add(item)
        await session.flush()
        return _read(item)


@router.put("/{template_id}", response_model=MessageTemplateRead)
async def update_message_template(
    template_id: UUID,
    payload: MessageTemplateUpdate,
    organization: Organization = Depends(get_organization),
) -> MessageTemplateRead:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        await transaction_lock(session, "message-template", stored_org.id)
        item = await _owned_template(session, stored_org, template_id)
        if payload.name is not None:
            requested = " ".join(payload.name.split()).strip()
            if requested and requested != item.name:
                existing = set(
                    (
                        await session.execute(
                            select(MessageTemplate.name).where(
                                MessageTemplate.organization_id == stored_org.id,
                                MessageTemplate.id != item.id,
                            )
                        )
                    ).scalars()
                )
                name = requested
                number = 2
                while name in existing:
                    name = f"{requested} {number}"
                    number += 1
                item.name = name
        if payload.translations is not None:
            current = normalize_translations(item.translations_json)
            for language, body in payload.translations.items():
                current[normalize_language(language)] = body.strip()
            item.translations_json = serialize_translations(current)
        if payload.is_default is True and not item.is_default:
            await session.execute(
                update(MessageTemplate)
                .where(
                    MessageTemplate.organization_id == stored_org.id,
                    MessageTemplate.id != item.id,
                    MessageTemplate.is_default.is_(True),
                )
                .values(is_default=False)
            )
            await session.flush()
            item.is_default = True
        await session.flush()
        return _read(item)


@router.post(
    "/{template_id}/translate-missing",
    response_model=MessageTemplateRead,
)
async def translate_missing_template_languages(
    template_id: UUID,
    payload: MessageTemplateTranslateRequest,
    organization: Organization = Depends(get_organization),
) -> MessageTemplateRead:
    if not translation.configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Automatic translation is not configured",
        )

    async with SessionLocal() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        item = await _owned_template(session, stored_org, template_id)
        snapshot = normalize_translations(item.translations_json)
        source_text = snapshot.get(payload.source_language)
        if not source_text:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The selected source language has no template text",
            )

    try:
        generated = await translation.translate_missing(
            source_text,
            source_language=payload.source_language,
            existing=snapshot,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Automatic translation failed",
        ) from exc

    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        await transaction_lock(session, "message-template", stored_org.id)
        item = await _owned_template(session, stored_org, template_id)
        current = normalize_translations(item.translations_json)
        if current.get(payload.source_language) != source_text:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Source template changed while translations were generated",
            )
        for language, body in generated.items():
            if language not in current:
                current[language] = body
        item.translations_json = serialize_translations(current)
        await session.flush()
        return _read(item)


@router.post(
    "/{template_id}/translate-other-languages",
    response_model=MessageTemplateRead,
)
async def translate_other_template_languages(
    template_id: UUID,
    payload: MessageTemplateTranslateRequest,
    organization: Organization = Depends(get_organization),
) -> MessageTemplateRead:
    if not translation.configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Automatic translation is not configured",
        )

    async with SessionLocal() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        item = await _owned_template(session, stored_org, template_id)
        snapshot = normalize_translations(item.translations_json)
        source_text = snapshot.get(payload.source_language)
        if not source_text:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The selected source language has no template text",
            )

    try:
        generated = await translation.translate_other_languages(
            source_text,
            source_language=payload.source_language,
            target_languages=list(SUPPORTED_LANGUAGES),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Automatic translation failed",
        ) from exc

    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        await transaction_lock(session, "message-template", stored_org.id)
        item = await _owned_template(session, stored_org, template_id)
        current = normalize_translations(item.translations_json)
        if current.get(payload.source_language) != source_text:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Source template changed while translations were generated",
            )
        current.update(generated)
        item.translations_json = serialize_translations(current)
        await session.flush()
        return _read(item)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_template(
    template_id: UUID,
    organization: Organization = Depends(get_organization),
) -> None:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        await transaction_lock(session, "message-template", stored_org.id)
        item = await _owned_template(session, stored_org, template_id)
        if item.is_default:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The default message template cannot be deleted",
            )
        await session.delete(item)
