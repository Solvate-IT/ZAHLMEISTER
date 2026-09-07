import pytest

from app.core.config import settings
from app.services.communications import (
    _effective_smtp_config,
    external_launch_uri,
    normalize_phone,
)


def test_external_mail_sms_whatsapp_uris_are_prefilled() -> None:
    mail, mail_select = external_launch_uri(
        "email", "anna@example.test", "Ausflug", "Bitte zahlen"
    )
    sms, sms_select = external_launch_uri("sms", "+43 660 123", None, "Bitte zahlen")
    whatsapp, whatsapp_select = external_launch_uri(
        "whatsapp", "+43 660 123", None, "Bitte zahlen"
    )
    assert mail.startswith("mailto:anna%40example.test?")
    assert "subject=Ausflug" in mail
    assert sms.startswith("sms:%2B43%20660%20123?body=")
    assert whatsapp.startswith("https://wa.me/43660123?text=")
    assert not mail_select and not sms_select and not whatsapp_select


def test_telegram_requires_saved_recipient() -> None:
    telegram, recipient_selection = external_launch_uri(
        "telegram", "@anna", None, "Bitte zahlen"
    )
    assert telegram == "https://t.me/anna"
    assert not recipient_selection
    with pytest.raises(ValueError, match="Telegram username missing"):
        external_launch_uri("telegram", "@", None, "Bitte zahlen")


def test_phone_normalization() -> None:
    assert normalize_phone("+43 (660) 12-34") == "+436601234"
    assert normalize_phone(None) == ""


def test_transport_requests_cannot_override_canonical_message() -> None:
    from pydantic import ValidationError

    from app.schemas.communications import ExternalDraftRequest, InternalMessageRequest

    for request_type in (ExternalDraftRequest, InternalMessageRequest):
        try:
            request_type(channel="email", body="provider-specific text")
        except ValidationError:
            pass
        else:
            raise AssertionError("Transport request accepted a message body override")


def test_partial_tenant_smtp_config_never_falls_back_to_platform(monkeypatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "platform.example.test")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "platform@example.test")
    monkeypatch.setattr(settings, "smtp_password", "platform-secret")
    monkeypatch.setattr(settings, "smtp_starttls", True)
    monkeypatch.setattr(settings, "mail_from_address", "platform@example.test")
    monkeypatch.setattr(settings, "mail_from_name", "Zahlmeister")

    tenant = _effective_smtp_config({"smtp_host": "tenant.example.test"})
    assert tenant == {"smtp_host": "tenant.example.test"}

    platform = _effective_smtp_config(
        {"from_name": "Example Organization", "reply_to": "reply@example.test"}
    )
    assert platform["smtp_host"] == "platform.example.test"
    assert platform["from_address"] == "platform@example.test"
    assert platform["from_name"] == "Example Organization"
