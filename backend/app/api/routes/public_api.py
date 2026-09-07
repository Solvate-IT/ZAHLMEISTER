from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_organization, get_session, require_api_scope
from app.api.routes.collections import create_collection, get_collection, list_collections
from app.api.routes.participant_lists import (
    add_participant, create_participant_list, get_participant_list, list_participant_lists,
)
from app.models.entities import Organization
from app.schemas.api_access import ExternalCollectionStatus
from app.schemas.workflow import (
    CollectionCreate, CollectionDetail, CollectionRead, ParticipantCreate, ParticipantListCreate,
    ParticipantListDetail, ParticipantListRead, ParticipantRead,
)

router = APIRouter()


@router.get("/participant-lists", response_model=list[ParticipantListRead], dependencies=[Depends(require_api_scope("participants:read"))])
async def external_list_participant_lists(organization: Organization = Depends(get_api_organization), session: AsyncSession = Depends(get_session)):
    return await list_participant_lists(organization=organization, session=session)


@router.post("/participant-lists", response_model=ParticipantListRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_scope("participants:write"))])
async def external_create_participant_list(payload: ParticipantListCreate, organization: Organization = Depends(get_api_organization)):
    return await create_participant_list(payload=payload, organization=organization)


@router.get("/participant-lists/{list_id}", response_model=ParticipantListDetail, dependencies=[Depends(require_api_scope("participants:read"))])
async def external_get_participant_list(list_id: UUID, organization: Organization = Depends(get_api_organization), session: AsyncSession = Depends(get_session)):
    return await get_participant_list(list_id=list_id, organization=organization, session=session)


@router.post("/participant-lists/{list_id}/participants", response_model=ParticipantRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_scope("participants:write"))])
async def external_add_participant(list_id: UUID, payload: ParticipantCreate, organization: Organization = Depends(get_api_organization)):
    return await add_participant(list_id=list_id, payload=payload, organization=organization)


@router.get("/collections", response_model=list[CollectionRead], dependencies=[Depends(require_api_scope("collections:read"))])
async def external_list_collections(organization: Organization = Depends(get_api_organization), session: AsyncSession = Depends(get_session)):
    return await list_collections(organization=organization, session=session)


@router.post("/collections", response_model=CollectionRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_scope("collections:write"))])
async def external_create_collection(payload: CollectionCreate, organization: Organization = Depends(get_api_organization)):
    return await create_collection(payload=payload, organization=organization)


@router.get("/collections/{collection_id}", response_model=CollectionDetail, dependencies=[Depends(require_api_scope("collections:read"))])
async def external_get_collection(collection_id: UUID, organization: Organization = Depends(get_api_organization), session: AsyncSession = Depends(get_session)):
    return await get_collection(collection_id=collection_id, organization=organization, session=session)


@router.get("/collections/{collection_id}/status", response_model=ExternalCollectionStatus, dependencies=[Depends(require_api_scope("payments:read"))])
async def external_collection_status(collection_id: UUID, organization: Organization = Depends(get_api_organization), session: AsyncSession = Depends(get_session)) -> ExternalCollectionStatus:
    item = await get_collection(collection_id=collection_id, organization=organization, session=session)
    total_amount = item.amount * item.participant_count
    return ExternalCollectionStatus(
        id=item.id, name=item.name, currency=item.currency, amount=str(item.amount),
        participant_count=item.participant_count, paid_count=item.paid_count,
        open_count=max(item.participant_count - item.paid_count, 0), paid_amount=str(item.paid_amount),
        total_amount=str(total_amount), status=item.status,
    )
