import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import public_contact
from app.schemas.contact import ContactRequest


def _payload(**overrides: str) -> ContactRequest:
    values = {
        "name": "Anna Muster",
        "email": "Anna@example.com",
        "subject": "Question",
        "message": "This is a sufficiently long contact message.",
        "locale": "de-AT",
        "website": "",
    }
    values.update(overrides)
    return ContactRequest(**values)


def test_contact_request_normalizes_fields() -> None:
    payload = _payload(name="  Anna   Muster ", email=" Anna@Example.COM ")
    assert payload.name == "Anna Muster"
    assert payload.email == "anna@example.com"


def test_contact_request_rejects_invalid_email_and_short_message() -> None:
    with pytest.raises(ValidationError):
        _payload(email="invalid")
    with pytest.raises(ValidationError):
        _payload(message="too short")


@pytest.mark.asyncio
async def test_contact_honeypot_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_if_called(**_: str) -> None:
        raise AssertionError("mail must not be sent for honeypot submissions")

    monkeypatch.setattr(public_contact, "send_platform_mail", fail_if_called)
    response = await public_contact.submit_contact(_payload(website="https://spam.example"))
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_contact_sends_to_configured_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, str] = {}

    async def fake_send(**kwargs: str) -> None:
        sent.update(kwargs)

    monkeypatch.setattr(public_contact, "send_platform_mail", fake_send)
    response = await public_contact.submit_contact(_payload())
    assert response.status_code == 204
    assert sent["recipient"] == public_contact.settings.contact_recipient
    assert "anna@example.com" in sent["body"]
    assert sent["subject"] == "Zahlmeister contact: Question"


@pytest.mark.asyncio
async def test_contact_returns_generic_error_on_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_send(**_: str) -> None:
        raise RuntimeError("smtp failure")

    monkeypatch.setattr(public_contact, "send_platform_mail", failing_send)
    with pytest.raises(HTTPException) as exc_info:
        await public_contact.submit_contact(_payload())
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Contact service is temporarily unavailable"
