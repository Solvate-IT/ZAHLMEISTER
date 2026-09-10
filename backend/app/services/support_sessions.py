from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import AuthSession, User
from app.services.auth import token_hash

SUPPORT_SESSION_MINUTES = 60
SUPPORT_TOKEN_PREFIX = "zms1"
_SUPPORT_CLOCK_SKEW_SECONDS = 60
_SUPPORT_TOKEN_MAX_LENGTH = 4096


@dataclass(frozen=True)
class SupportSessionClaims:
    user_id: UUID
    admin_user_id: UUID
    organization_id: UUID
    issued_at: datetime
    expires_at: datetime
    read_only: bool = True


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * ((-len(value)) % 4)))


def _signature(message: bytes) -> bytes:
    return hmac.new(settings.app_secret.encode("utf-8"), message, hashlib.sha256).digest()


def _payload(
    *,
    user_id: UUID,
    admin_user_id: UUID,
    organization_id: UUID,
    issued_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    return {
        "typ": "support",
        "uid": str(user_id),
        "aid": str(admin_user_id),
        "oid": str(organization_id),
        "ro": True,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(12),
    }


def build_support_token(
    *,
    user_id: UUID,
    admin_user_id: UUID,
    organization_id: UUID,
    issued_at: datetime,
    expires_at: datetime,
) -> str:
    encoded = _b64url(
        json.dumps(
            _payload(
                user_id=user_id,
                admin_user_id=admin_user_id,
                organization_id=organization_id,
                issued_at=issued_at,
                expires_at=expires_at,
            ),
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    signing_input = f"{SUPPORT_TOKEN_PREFIX}.{encoded}".encode("ascii")
    return f"{SUPPORT_TOKEN_PREFIX}.{encoded}.{_b64url(_signature(signing_input))}"


def decode_support_token(
    token: str,
    *,
    now: datetime | None = None,
) -> SupportSessionClaims | None:
    if not token.startswith(f"{SUPPORT_TOKEN_PREFIX}."):
        return None
    if len(token) > _SUPPORT_TOKEN_MAX_LENGTH:
        raise ValueError("Invalid support session")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid support session")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    try:
        supplied_signature = _b64url_decode(parts[2])
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ValueError("Invalid support session") from exc
    if not hmac.compare_digest(_signature(signing_input), supplied_signature):
        raise ValueError("Invalid support session")
    try:
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Invalid support session")
        if payload.get("typ") != "support" or payload.get("ro") is not True:
            raise ValueError("Invalid support session")
        user_id = UUID(str(payload["uid"]))
        admin_user_id = UUID(str(payload["aid"]))
        organization_id = UUID(str(payload["oid"]))
        issued_at = datetime.fromtimestamp(int(payload["iat"]), tz=UTC)
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as exc:
        raise ValueError("Invalid support session") from exc

    current = now or datetime.now(UTC)
    maximum_ttl = timedelta(minutes=SUPPORT_SESSION_MINUTES, seconds=_SUPPORT_CLOCK_SKEW_SECONDS)
    if expires_at <= issued_at or expires_at - issued_at > maximum_ttl:
        raise ValueError("Invalid support session")
    if issued_at > current + timedelta(seconds=_SUPPORT_CLOCK_SKEW_SECONDS):
        raise ValueError("Invalid support session")
    if expires_at <= current:
        raise ValueError("Support session expired")

    return SupportSessionClaims(
        user_id=user_id,
        admin_user_id=admin_user_id,
        organization_id=organization_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )


async def create_support_session(
    session: AsyncSession,
    *,
    target_user: User,
    admin_user: User,
) -> tuple[str, AuthSession, SupportSessionClaims]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=SUPPORT_SESSION_MINUTES)
    token = build_support_token(
        user_id=target_user.id,
        admin_user_id=admin_user.id,
        organization_id=target_user.organization_id,
        issued_at=now,
        expires_at=expires_at,
    )
    auth_session = AuthSession(
        user_id=target_user.id,
        token_hash=token_hash(token),
        expires_at=expires_at,
    )
    session.add(auth_session)
    await session.flush()
    claims = decode_support_token(token, now=now)
    if claims is None:  # pragma: no cover - build_support_token always creates support tokens
        raise RuntimeError("Support session could not be created")
    return token, auth_session, claims


def support_request_is_allowed(method: str, path: str) -> bool:
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return True
    normalized = path.rstrip("/")
    return normalized in {"/auth/support-logout", "/api/v1/auth/support-logout"}
