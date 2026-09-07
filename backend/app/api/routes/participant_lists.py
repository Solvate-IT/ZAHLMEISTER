import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_organization, get_session
from app.db.session import SessionLocal
from app.models.entities import Organization, Participant, ParticipantList
from app.schemas.workflow import (
    ParticipantChannelRead,
    ParticipantChannelUpdate,
    ParticipantCreate,
    ParticipantListCreate,
    ParticipantListDetail,
    ParticipantListRead,
    ParticipantListUpdate,
    ParticipantRead,
    ParticipantUpdate,
)
from app.services.channel_strategy import (
    SUPPORTED_CHANNELS,
    channel_addresses,
    effective_availability,
    load_participant_channel_settings,
    reset_channel_knowledge,
    set_channel_knowledge,
)
from app.services.naming import unique_participant_list_name
from app.services.plans import FREE_PARTICIPANTS_PER_LIST, participant_capacity_available

router = APIRouter(prefix="/participant-lists", tags=["participant-lists"])


def _participant_read(participant: Participant, overrides: dict | None = None) -> ParticipantRead:
    overrides = overrides or {}
    return ParticipantRead(
        id=participant.id,
        name=participant.name,
        email=participant.email,
        phone=participant.phone,
        channel_addresses=channel_addresses(participant),
        channels=[
            ParticipantChannelRead(
                channel=channel,
                enabled=bool(overrides.get(channel).enabled) if overrides.get(channel) else True,
                availability=effective_availability(participant, channel, overrides.get(channel)),
                learned=overrides.get(channel) is not None,
            )
            for channel in SUPPORTED_CHANNELS
        ],
    )


def _participant_values(
    payload: ParticipantCreate | ParticipantUpdate,
) -> tuple[str | None, str | None, str]:
    email = (payload.email or "").strip() or None
    phone = (payload.phone or "").strip() or None
    phone_digits = "".join(char for char in (phone or "") if char.isdigit())
    return email, phone, phone_digits


async def _duplicate_participant(
    session: AsyncSession,
    list_id: UUID,
    payload: ParticipantCreate | ParticipantUpdate,
    *,
    exclude_id: UUID | None = None,
) -> Participant | None:
    email, _, phone_digits = _participant_values(payload)
    rows = (
        await session.execute(select(Participant).where(Participant.list_id == list_id))
    ).scalars().all()
    return next(
        (
            row
            for row in rows
            if row.id != exclude_id
            and row.name.casefold() == payload.name.casefold()
            and (row.email or "").casefold() == (email or "").casefold()
            and "".join(char for char in (row.phone or "") if char.isdigit()) == phone_digits
        ),
        None,
    )


async def _owned_list(
    session: AsyncSession,
    organization: Organization,
    list_id: UUID,
    *,
    for_update: bool = False,
) -> ParticipantList:
    item = await session.get(ParticipantList, list_id, with_for_update=for_update)
    if item is None or item.organization_id != organization.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Participant list not found"
        )
    return item


async def _owned_participant(
    session: AsyncSession,
    organization: Organization,
    list_id: UUID,
    participant_id: UUID,
    *,
    for_update: bool = False,
) -> tuple[ParticipantList, Participant]:
    item = await _owned_list(session, organization, list_id, for_update=for_update)
    participant = await session.get(Participant, participant_id, with_for_update=for_update)
    if participant is None or participant.list_id != item.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    return item, participant


@router.get("", response_model=list[ParticipantListRead])
async def list_participant_lists(
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> list[ParticipantListRead]:
    count_expr = func.count(Participant.id)
    stmt = (
        select(ParticipantList, count_expr)
        .outerjoin(Participant, Participant.list_id == ParticipantList.id)
        .where(ParticipantList.organization_id == organization.id)
        .group_by(ParticipantList.id)
        .order_by(ParticipantList.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        ParticipantListRead(id=item.id, name=item.name, participant_count=count)
        for item, count in rows
    ]


@router.post("", response_model=ParticipantListRead, status_code=status.HTTP_201_CREATED)
async def create_participant_list(
    payload: ParticipantListCreate,
    organization: Organization = Depends(get_organization),
) -> ParticipantListRead:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        name = await unique_participant_list_name(session, stored_org, payload.name)
        item = ParticipantList(organization_id=stored_org.id, name=name)
        session.add(item)
        await session.flush()
        return ParticipantListRead(id=item.id, name=item.name, participant_count=0)


@router.get("/{list_id}", response_model=ParticipantListDetail)
async def get_participant_list(
    list_id: UUID,
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> ParticipantListDetail:
    item = await _owned_list(session, organization, list_id)
    participants = (
        await session.execute(
            select(Participant)
            .where(Participant.list_id == item.id)
            .order_by(Participant.name, Participant.created_at)
        )
    ).scalars().all()
    overrides = await load_participant_channel_settings(
        session, [participant.id for participant in participants]
    )
    return ParticipantListDetail(
        id=item.id,
        name=item.name,
        participant_count=len(participants),
        participants=[
            _participant_read(participant, overrides.get(participant.id))
            for participant in participants
        ],
    )


@router.patch("/{list_id}", response_model=ParticipantListRead)
async def update_participant_list(
    list_id: UUID,
    payload: ParticipantListUpdate,
    organization: Organization = Depends(get_organization),
) -> ParticipantListRead:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        item = await _owned_list(session, stored_org, list_id, for_update=True)
        item.name = await unique_participant_list_name(
            session, stored_org, payload.name, exclude_id=item.id
        )
        count = await session.scalar(select(func.count()).where(Participant.list_id == item.id))
        return ParticipantListRead(id=item.id, name=item.name, participant_count=count or 0)


@router.post(
    "/{list_id}/participants",
    response_model=ParticipantRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_participant(
    list_id: UUID,
    payload: ParticipantCreate,
    organization: Organization = Depends(get_organization),
) -> ParticipantRead:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        item = await _owned_list(session, stored_org, list_id, for_update=True)
        if not await participant_capacity_available(session, stored_org.id, item.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Free plan supports up to {FREE_PARTICIPANTS_PER_LIST} participants per list",
            )
        email, phone, _ = _participant_values(payload)
        duplicate = await _duplicate_participant(session, item.id, payload)
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Participant already exists"
            )
        participant = Participant(
            list_id=item.id,
            name=payload.name,
            email=email,
            phone=phone,
            channel_addresses_json=json.dumps(payload.channel_addresses or {}, ensure_ascii=False),
        )
        session.add(participant)
        await session.flush()
        await session.refresh(participant)
        return _participant_read(participant)


@router.patch(
    "/{list_id}/participants/{participant_id}",
    response_model=ParticipantRead,
)
async def update_participant(
    list_id: UUID,
    participant_id: UUID,
    payload: ParticipantUpdate,
    organization: Organization = Depends(get_organization),
) -> ParticipantRead:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        item, participant = await _owned_participant(
            session, stored_org, list_id, participant_id, for_update=True
        )
        duplicate = await _duplicate_participant(
            session, item.id, payload, exclude_id=participant.id
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Participant already exists"
            )
        email, phone, _ = _participant_values(payload)
        old_email = participant.email
        old_phone = participant.phone
        old_addresses = channel_addresses(participant)
        participant.name = payload.name
        participant.email = email
        participant.phone = phone
        participant.channel_addresses_json = json.dumps(
            payload.channel_addresses or {}, ensure_ascii=False
        )
        if (old_email or "").casefold() != (email or "").casefold():
            await reset_channel_knowledge(session, participant.id, "email")
        if old_phone != phone:
            await reset_channel_knowledge(session, participant.id, "whatsapp")
            await reset_channel_knowledge(session, participant.id, "sms")
        if old_addresses.get("telegram") != (payload.channel_addresses or {}).get("telegram"):
            await reset_channel_knowledge(session, participant.id, "telegram")
        await session.flush()
        await session.refresh(participant)
        overrides = await load_participant_channel_settings(session, [participant.id])
        return _participant_read(participant, overrides.get(participant.id))


@router.patch(
    "/{list_id}/participants/{participant_id}/channels/{channel}",
    response_model=ParticipantRead,
)
async def update_participant_channel(
    list_id: UUID,
    participant_id: UUID,
    channel: str,
    payload: ParticipantChannelUpdate,
    organization: Organization = Depends(get_organization),
) -> ParticipantRead:
    if channel not in SUPPORTED_CHANNELS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown channel")
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        _item, participant = await _owned_participant(
            session, stored_org, list_id, participant_id, for_update=True
        )
        try:
            await set_channel_knowledge(
                session,
                participant.id,
                channel,
                enabled=payload.enabled,
                availability=payload.availability,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        overrides = await load_participant_channel_settings(session, [participant.id])
        return _participant_read(participant, overrides.get(participant.id))


@router.delete("/{list_id}/participants/{participant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_participant(
    list_id: UUID,
    participant_id: UUID,
    organization: Organization = Depends(get_organization),
) -> None:
    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        _item, participant = await _owned_participant(
            session, stored_org, list_id, participant_id
        )
        await session.delete(participant)
