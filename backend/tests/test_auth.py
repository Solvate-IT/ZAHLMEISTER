from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

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


def test_registration_requires_explicit_terms_acceptance() -> None:
    from pydantic import ValidationError

    from app.schemas.auth import RegisterRequest

    base = {"email": "anna@example.test", "password": "correct-horse-7"}
    for missing_or_refused in ({}, {"accept_terms": False}):
        with pytest.raises(ValidationError):
            RegisterRequest(**base, **missing_or_refused)
    assert RegisterRequest(**base, accept_terms=True).accept_terms is True


@pytest.mark.asyncio
async def test_registration_records_when_and_which_terms_were_accepted(monkeypatch) -> None:
    from fastapi import BackgroundTasks

    from app.api.routes import auth as auth_routes
    from app.core.legal import TERMS_VERSION
    from app.models.entities import User
    from app.schemas.auth import RegisterRequest

    added = []

    class Session:
        async def scalar(self, _statement):
            return None

        def add(self, value):
            if getattr(value, "id", None) is None:
                value.id = uuid4()
            added.append(value)

        async def flush(self):
            pass

    session = Session()
    factory = MagicMock()
    factory.begin.return_value.__aenter__.return_value = session
    monkeypatch.setattr(auth_routes, "SessionLocal", factory)

    async def token(*_args, **_kwargs):
        return "token"

    monkeypatch.setattr(auth_routes, "create_action_token", token)
    monkeypatch.setattr(auth_routes, "create_auth_session", token)
    monkeypatch.setattr(auth_routes, "auth_response", lambda *_args: "response")

    await auth_routes.register(
        RegisterRequest(email="anna@example.test", password="correct-horse-7", accept_terms=True),
        BackgroundTasks(),
    )
    user = next(item for item in added if isinstance(item, User))
    assert user.terms_accepted_at is not None
    assert user.terms_version == TERMS_VERSION
