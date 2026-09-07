from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_organization, get_session
from app.models.entities import ApiCredential, Organization
from app.schemas.api_access import (
    API_SCOPES, ApiCredentialCreate, ApiCredentialCreated, ApiCredentialRead,
    ApiEnabledUpdate, ApiSettingsRead,
)
from app.services.api_access import credential_read, encode_scopes, issue_api_token

router = APIRouter(prefix="/account/api", tags=["api-access"])


@router.get("", response_model=ApiSettingsRead)
async def get_api_settings(organization: Organization = Depends(get_organization)) -> ApiSettingsRead:
    return ApiSettingsRead(enabled=organization.api_enabled, available_scopes=sorted(API_SCOPES))


@router.put("/enabled", response_model=ApiSettingsRead)
async def set_api_enabled(
    payload: ApiEnabledUpdate,
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> ApiSettingsRead:
    stored = await session.get(Organization, organization.id, with_for_update=True)
    assert stored is not None
    stored.api_enabled = payload.enabled
    await session.commit()
    return ApiSettingsRead(enabled=stored.api_enabled, available_scopes=sorted(API_SCOPES))


@router.get("/credentials", response_model=list[ApiCredentialRead])
async def list_api_credentials(
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> list[ApiCredentialRead]:
    items = (await session.execute(
        select(ApiCredential).where(ApiCredential.organization_id == organization.id).order_by(ApiCredential.created_at.desc())
    )).scalars().all()
    return [credential_read(item) for item in items]


@router.post("/credentials", response_model=ApiCredentialCreated, status_code=status.HTTP_201_CREATED)
async def create_api_credential(
    payload: ApiCredentialCreate,
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> ApiCredentialCreated:
    if not organization.api_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enable API access first")
    if payload.expires_at is not None and payload.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Expiration must be in the future")
    raw, hashed, prefix = issue_api_token()
    item = ApiCredential(
        organization_id=organization.id, name=payload.name, token_hash=hashed, token_prefix=prefix,
        scopes_json=encode_scopes(payload.scopes), expires_at=payload.expires_at,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    base = credential_read(item)
    return ApiCredentialCreated(**base.model_dump(), token=raw)


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_credential(
    credential_id: UUID,
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> None:
    item = await session.get(ApiCredential, credential_id, with_for_update=True)
    if item is None or item.organization_id != organization.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API credential not found")
    if item.revoked_at is None:
        item.revoked_at = datetime.now(UTC)
        await session.commit()
