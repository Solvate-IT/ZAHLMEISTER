from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.schemas.passwords import validate_password_strength
from app.services.auth import (
    ADMIN_SESSION_HOURS,
    hash_password,
    is_platform_admin,
    normalize_email,
    token_hash,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("very-secret-password")
    assert hashed != "very-secret-password"
    assert verify_password(hashed, "very-secret-password")
    assert not verify_password(hashed, "wrong-password")


def test_password_policy_accepts_six_characters_with_letter_and_number() -> None:
    assert validate_password_strength("abc123") == "abc123"


@pytest.mark.parametrize("password", ["abc12", "abcdef", "123456"])
def test_password_policy_rejects_weak_passwords(password: str) -> None:
    with pytest.raises(ValueError, match="at least 6 characters"):
        validate_password_strength(password)


def test_email_and_token_normalization() -> None:
    assert normalize_email(" User@Example.COM ") == "user@example.com"
    assert token_hash("abc") == token_hash("abc")
    assert token_hash("abc") != token_hash("def")


def test_auth_response_exposes_organization_name() -> None:
    import uuid

    from app.models.entities import Organization, User
    from app.services.auth import auth_response

    organization_id = uuid.uuid4()
    organization = Organization(
        id=organization_id,
        name="Muster Verein",
        locale="de-AT",
        currency="EUR",
    )
    user = User(
        id=uuid.uuid4(),
        organization_id=organization_id,
        email="anna@example.com",
        display_name="Anna",
        password_hash="unused",
    )

    response = auth_response("token", user, organization)

    assert response.user.organization_name == "Muster Verein"


def test_platform_admin_requires_verified_active_allowlisted_user(monkeypatch) -> None:
    import uuid

    from app.models.entities import User

    monkeypatch.setattr(settings, "platform_admin_emails_raw", "admin@example.com")
    user = User(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        email="admin@example.com",
        display_name="Admin",
        password_hash="unused",
        is_active=True,
    )

    assert not is_platform_admin(user)
    user.email_verified_at = datetime.now(UTC)
    assert is_platform_admin(user)
    user.is_active = False
    assert not is_platform_admin(user)


def test_admin_sessions_are_short_lived() -> None:
    assert ADMIN_SESSION_HOURS == 8
