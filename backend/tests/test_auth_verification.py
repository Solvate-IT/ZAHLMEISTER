from datetime import UTC, datetime
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.routes import auth
from app.models.entities import Organization, User
from app.schemas.account import TokenRequest


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _VerificationWriteSession:
    def __init__(self):
        self.flushed = False

    async def flush(self):
        self.flushed = True


class _VerificationReadSession:
    def __init__(self, persisted_at):
        self.persisted_at = persisted_at
        self.read = False

    async def scalar(self, _statement):
        self.read = True
        return self.persisted_at


class _VerificationSessionFactory:
    def __init__(self, write_session, read_session):
        self.write_session = write_session
        self.read_session = read_session

    def begin(self):
        return _Context(self.write_session)

    def __call__(self):
        return _Context(self.read_session)


@pytest.mark.asyncio
async def test_verify_email_only_reports_success_after_persisted_state(monkeypatch) -> None:
    user = SimpleNamespace(id=uuid.uuid4(), email_verified_at=None)
    write_session = _VerificationWriteSession()
    persisted_at = datetime.now(UTC)
    read_session = _VerificationReadSession(persisted_at)
    monkeypatch.setattr(
        auth,
        "SessionLocal",
        _VerificationSessionFactory(write_session, read_session),
    )

    async def consume(_session, _token, _purpose):
        return user

    monkeypatch.setattr(auth, "consume_action_token", consume)

    result = await auth.verify_email(TokenRequest(token="x" * 40))

    assert result.status == "verified"
    assert user.email_verified_at is not None
    assert write_session.flushed is True
    assert read_session.read is True


@pytest.mark.asyncio
async def test_resend_verification_reports_already_verified_without_sending(monkeypatch) -> None:
    user = SimpleNamespace(id=uuid.uuid4(), email_verified_at=datetime.now(UTC))

    async def unexpected_send(*_args, **_kwargs):
        raise AssertionError("verification email must not be sent")

    monkeypatch.setattr(auth, "_send_verification", unexpected_send)

    result = await auth.resend_verification(user=user)

    assert result.status == "already_verified"


class _ResendSession:
    def __init__(self, stored_user, organization):
        self.stored_user = stored_user
        self.organization = organization

    async def get(self, model, _identifier):
        if model is User:
            return self.stored_user
        if model is Organization:
            return self.organization
        raise AssertionError(f"unexpected model: {model}")


class _ResendSessionFactory:
    def __init__(self, session):
        self.session = session

    def begin(self):
        return _Context(self.session)


@pytest.mark.asyncio
async def test_resend_verification_awaits_mail_delivery(monkeypatch) -> None:
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    current_user = SimpleNamespace(id=user_id, email_verified_at=None)
    stored_user = SimpleNamespace(
        id=user_id,
        organization_id=organization_id,
        email="anna@example.com",
        email_verified_at=None,
    )
    organization = SimpleNamespace(id=organization_id, locale="de")
    monkeypatch.setattr(
        auth,
        "SessionLocal",
        _ResendSessionFactory(_ResendSession(stored_user, organization)),
    )

    async def create_token(_session, _user, _purpose, *, ttl):
        assert ttl.total_seconds() == 24 * 60 * 60
        return "verification-token"

    sent = {}

    async def send(email, token, locale):
        sent.update(email=email, token=token, locale=locale)

    monkeypatch.setattr(auth, "create_action_token", create_token)
    monkeypatch.setattr(auth, "_send_verification", send)

    result = await auth.resend_verification(user=current_user)

    assert result.status == "sent"
    assert sent == {
        "email": "anna@example.com",
        "token": "verification-token",
        "locale": "de",
    }


def test_verified_action_guard_accepts_verified_user() -> None:
    user = SimpleNamespace(email_verified_at=datetime.now(UTC))
    assert deps.ensure_verified_email(user) is user


def test_verified_action_guard_rejects_unverified_user() -> None:
    user = SimpleNamespace(email_verified_at=None)
    with pytest.raises(HTTPException) as exc:
        deps.ensure_verified_email(user)
    assert exc.value.status_code == 403
    assert exc.value.detail == "Email verification required"
