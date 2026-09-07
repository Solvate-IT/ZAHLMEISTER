import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuthSession, Organization, User
from app.schemas.auth import AuthResponse, UserRead

_password_hasher = PasswordHasher()
SESSION_DAYS = 30


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_auth_session(session: AsyncSession, user: User) -> str:
    token = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=_hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(days=SESSION_DAYS),
    )
    session.add(auth_session)
    await session.flush()
    return token


def token_hash(token: str) -> str:
    return _hash_token(token)


def auth_response(token: str, user: User, organization: Organization) -> AuthResponse:
    return AuthResponse(
        token=token,
        user=UserRead(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            organization_id=str(user.organization_id),
            organization_name=organization.name,
            locale=organization.locale,
            currency=organization.currency,
            email_verified=user.email_verified_at is not None,
        ),
    )
