from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.entities import ApiCredential, AuthSession, Organization, User
from app.services.api_access import credential_is_active, decode_scopes
from app.services.auth import (
    ADMIN_REQUEST_HEADER,
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_HOURS,
    ADMIN_TOKEN_PREFIX,
    is_platform_admin,
    token_hash,
)
from app.services.support_sessions import decode_support_token, support_request_is_allowed

bearer_scheme = HTTPBearer(auto_error=False)


async def get_session():
    async with SessionLocal() as session:
        yield session


async def get_current_auth_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> AuthSession:
    request.state.support_session = None
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    token = credentials.credentials
    if token.startswith(ADMIN_TOKEN_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    try:
        support_claims = decode_support_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired") from exc

    auth_session = await session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash(token),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    if support_claims is not None:
        if auth_session.user_id != support_claims.user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
        target_user = await session.get(User, support_claims.user_id)
        admin_user = await session.get(User, support_claims.admin_user_id)
        if (
            target_user is None
            or not target_user.is_active
            or target_user.organization_id != support_claims.organization_id
            or admin_user is None
            or not is_platform_admin(admin_user)
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
        if auth_session.expires_at > support_claims.expires_at + timedelta(seconds=1):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
        if not support_request_is_allowed(request.method, request.url.path):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Support view is read-only",
            )
        request.state.support_session = support_claims

    return auth_session


async def get_current_admin_auth_session(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthSession:
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not token or not token.startswith(ADMIN_TOKEN_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required")
    auth_session = await session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash(token),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session expired")
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
    request: Request,
    auth_session: AuthSession = Depends(get_current_admin_auth_session),
    session: AsyncSession = Depends(get_session),
) -> User:
    if request.headers.get(ADMIN_REQUEST_HEADER) != "1":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin request")
    user = await session.get(User, auth_session.user_id)
    if user is None or not is_platform_admin(user):
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
