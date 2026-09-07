from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_organization
from app.db.session import SessionLocal
from app.models.entities import MessageTemplate, Organization
from app.schemas.templates import (
    MessageTemplateCreate,
    MessageTemplateRead,
    MessageTemplateUpdate,
    TemplateVariableRead,
)
from app.services.locks import transaction_lock
from app.services.templates import (
    TEMPLATE_VARIABLES,
    default_template_name,
    default_template_translations,
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
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        await ensure_default_template(session, stored_org)
        item = MessageTemplate(
            organization_id=stored_org.id,
            name=await _unique_name(session, stored_org, payload.name),
            translations_json=serialize_translations(default_template_translations()),
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
                current[language.split("-", 1)[0].lower()] = body.strip()
            item.translations_json = serialize_translations(current)
        if payload.is_default is True and not item.is_default:
            others = (
                await session.execute(
                    select(MessageTemplate).where(
                        MessageTemplate.organization_id == stored_org.id,
                        MessageTemplate.id != item.id,
                        MessageTemplate.is_default.is_(True),
                    )
                )
            ).scalars().all()
            for other in others:
                other.is_default = False
            item.is_default = True
        await session.flush()
        return _read(item)
