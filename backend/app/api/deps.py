from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.entities import ApiCredential, AuthSession, Organization, User
from app.services.api_access import credential_is_active, decode_scopes
from app.services.auth import ADMIN_SESSION_HOURS, is_platform_admin, token_hash

bearer_scheme = HTTPBearer(auto_error=False)


async def get_session():
    async with SessionLocal() as session:
        yield session


async def get_current_auth_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> AuthSession:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    auth_session = await session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash(credentials.credentials),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return auth_session


async def get_current_user(
    auth_session: AuthSession = Depends(get_current_auth_session),
    session: AsyncSession = Depends(get_session),
) -> User:
    user = await session.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    return user


async def require_platform_admin(
    auth_session: AuthSession = Depends(get_current_auth_session),
    user: User = Depends(get_current_user),
) -> User:
    if not is_platform_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin required")
    if auth_session.created_at is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session expired")
    maximum_ttl = timedelta(hours=ADMIN_SESSION_HOURS, minutes=1)
    if auth_session.expires_at - auth_session.created_at > maximum_ttl:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session required")
    return user


async def get_organization(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Organization:
    organization = await session.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return organization


async def get_api_credential(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> ApiCredential:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API authentication required")
    item = await session.scalar(
        select(ApiCredential).where(ApiCredential.token_hash == token_hash(credentials.credentials))
    )
    if item is None or not credential_is_active(item):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API credential")
    organization = await session.get(Organization, item.organization_id)
    if organization is None or not organization.api_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API access is disabled")
    now = datetime.now(UTC)
    if item.last_used_at is None or item.last_used_at < now - timedelta(minutes=5):
        item.last_used_at = now
        await session.commit()
    return item


async def get_api_organization(
    credential: ApiCredential = Depends(get_api_credential),
    session: AsyncSession = Depends(get_session),
) -> Organization:
    organization = await session.get(Organization, credential.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return organization


def require_api_scope(scope: str):
    async def dependency(credential: ApiCredential = Depends(get_api_credential)) -> ApiCredential:
        if scope not in decode_scopes(credential.scopes_json):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing API scope: {scope}")
        return credential
    return dependency
