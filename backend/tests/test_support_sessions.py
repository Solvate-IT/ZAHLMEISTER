from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services.auth import ADMIN_TOKEN_PREFIX
from app.services.support_sessions import (
    SUPPORT_SESSION_MINUTES,
    build_support_token,
    decode_support_token,
    support_request_is_allowed,
)


def _token(now: datetime) -> tuple[str, object, object, object]:
    user_id = uuid4()
    admin_user_id = uuid4()
    organization_id = uuid4()
    token = build_support_token(
        user_id=user_id,
        admin_user_id=admin_user_id,
        organization_id=organization_id,
        issued_at=now,
        expires_at=now + timedelta(minutes=SUPPORT_SESSION_MINUTES),
    )
    return token, user_id, admin_user_id, organization_id


def test_support_token_is_signed_scoped_and_read_only(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_secret", "test-support-secret")
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    token, user_id, admin_user_id, organization_id = _token(now)

    claims = decode_support_token(token, now=now + timedelta(minutes=5))

    assert claims is not None
    assert claims.user_id == user_id
    assert claims.admin_user_id == admin_user_id
    assert claims.organization_id == organization_id
    assert claims.read_only is True
    assert claims.expires_at == now + timedelta(minutes=SUPPORT_SESSION_MINUTES)


def test_support_token_tampering_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_secret", "test-support-secret")
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    token, _, _, _ = _token(now)
    prefix, payload, signature = token.split(".")
    replacement = "A" if payload[-1] != "A" else "B"
    tampered = f"{prefix}.{payload[:-1]}{replacement}.{signature}"

    with pytest.raises(ValueError, match="Invalid support session"):
        decode_support_token(tampered, now=now)


def test_expired_support_token_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_secret", "test-support-secret")
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    token = build_support_token(
        user_id=uuid4(),
        admin_user_id=uuid4(),
        organization_id=uuid4(),
        issued_at=now - timedelta(minutes=61),
        expires_at=now - timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="expired"):
        decode_support_token(token, now=now)


def test_normal_session_is_not_misclassified_as_support() -> None:
    assert decode_support_token("ordinary-customer-session") is None


def test_support_requests_are_read_only_except_explicit_logout() -> None:
    assert support_request_is_allowed("GET", "/api/v1/collections")
    assert support_request_is_allowed("HEAD", "/api/v1/collections")
    assert support_request_is_allowed("OPTIONS", "/api/v1/collections")
    assert support_request_is_allowed("POST", "/api/v1/auth/support-logout")
    assert not support_request_is_allowed("POST", "/api/v1/collections")
    assert not support_request_is_allowed("PATCH", "/api/v1/account/profile")
    assert not support_request_is_allowed("DELETE", "/api/v1/participant-lists/123")


def test_platform_admin_tokens_have_a_dedicated_namespace() -> None:
    assert ADMIN_TOKEN_PREFIX == "zma1."
