from __future__ import annotations

import base64
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.schemas.communications import ChannelSettingUpdate
from app.services import microsoft365, ponto
from app.services.bank_sync import parse_ponto_account, parse_ponto_transaction
from app.services.bank_sync_providers import get_bank_sync_provider
from app.services.channel_config import canonical_internal_provider, internal_channel_configured
from app.services.communications import _test_smtp_imap
from app.services.message_renderer import CanonicalMessage


def test_ponto_account_parser_handles_json_api_attributes() -> None:
    parsed = parse_ponto_account(
        {
            "id": "acc-1",
            "attributes": {
                "description": "Vereinskonto",
                "reference": "AT611904300234573201",
                "currency": "EUR",
            },
        }
    )
    assert parsed == {
        "external_id": "acc-1",
        "name": "Vereinskonto",
        "iban": "AT611904300234573201",
        "currency": "EUR",
    }


def test_ponto_transaction_parser_keeps_matching_information() -> None:
    parsed = parse_ponto_transaction(
        {
            "id": "tx-1",
            "attributes": {
                "amount": "12.00",
                "currency": "EUR",
                "executionDate": "2026-09-06T08:15:00Z",
                "counterpartName": "Anna Muster",
                "remittanceInformation": "Schulausflug ZM-ABC123",
                "endToEndId": "E2E-1",
            },
        }
    )
    assert parsed is not None
    assert parsed.amount == Decimal("12.00")
    assert parsed.counterparty_name == "Anna Muster"
    assert parsed.reference and "ZM-ABC123" in parsed.reference
    assert parsed.bank_transaction_id == "tx-1"


def test_ponto_transaction_parser_ignores_outgoing_payments() -> None:
    parsed = parse_ponto_transaction(
        {"id": "tx-2", "attributes": {"amount": "-12.00", "currency": "EUR"}}
    )
    assert parsed is None


def test_ponto_oauth_state_roundtrip() -> None:
    state = ponto.sign_state(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )
    assert ponto.verify_state(state) == (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )


def test_ponto_sandbox_authorization_url_is_selected(monkeypatch) -> None:
    monkeypatch.setattr(ponto.settings, "ponto_connect_environment", "sandbox")
    monkeypatch.setattr(ponto.settings, "ponto_connect_authorize_url", "")
    assert (
        ponto.settings.ponto_authorization_url
        == "https://sandbox-authorization.myponto.com/oauth2/auth"
    )


def test_ponto_live_authorization_url_is_selected(monkeypatch) -> None:
    monkeypatch.setattr(ponto.settings, "ponto_connect_environment", "live")
    monkeypatch.setattr(ponto.settings, "ponto_connect_authorize_url", "")
    assert ponto.settings.ponto_authorization_url == "https://authorization.myponto.com/oauth2/auth"


def test_ponto_configuration_status_reports_missing_and_ready(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ponto.settings, "ponto_connect_client_id", "client-id")
    monkeypatch.setattr(ponto.settings, "ponto_connect_client_secret", "client-secret")
    monkeypatch.setattr(ponto.settings, "ponto_connect_cert_path", "")
    monkeypatch.setattr(ponto.settings, "ponto_connect_key_path", "")
    missing = ponto.configuration_status()
    assert missing["configured"] is False
    assert "client_certificate" in missing["missing"]
    assert "private_key" in missing["missing"]

    cert = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    cert.write_text("test certificate")
    key.write_text("test private key")
    monkeypatch.setattr(ponto.settings, "ponto_connect_cert_path", str(cert))
    monkeypatch.setattr(ponto.settings, "ponto_connect_key_path", str(key))
    ready = ponto.configuration_status()
    assert ready["configured"] is True
    assert ready["missing"] == []


def test_production_rejects_ponto_sandbox_configuration(monkeypatch) -> None:
    monkeypatch.setattr(ponto.settings, "environment", "production")
    monkeypatch.setattr(ponto.settings, "ponto_connect_environment", "sandbox")
    monkeypatch.setattr(ponto.settings, "ponto_connect_client_id", "sandbox-client")
    errors = ponto.settings.production_security_errors()
    assert "PONTO_CONNECT_ENVIRONMENT must be live in production" in errors


def test_production_requires_explicit_oauth_callback_base(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "oauth_callback_base_url", "")
    errors = settings.production_security_errors()
    assert "OAUTH_CALLBACK_BASE_URL must be explicitly configured in production" in errors


def test_bank_sync_provider_registry_is_replaceable() -> None:
    provider = get_bank_sync_provider("ponto")
    assert provider.name == "ponto"


def test_smtp_imap_connection_test_supports_standard_tls(monkeypatch) -> None:
    calls: list[str] = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            calls.append(f"smtp:{host}:{port}")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            calls.append("smtp:starttls")

        def login(self, username, password):
            calls.append(f"smtp:login:{username}")

        def noop(self):
            calls.append("smtp:noop")

    class FakeImap:
        def __init__(self, host, port):
            calls.append(f"imap:{host}:{port}")

        def login(self, username, password):
            calls.append(f"imap:login:{username}")

        def select(self, folder, readonly=True):
            calls.append(f"imap:select:{folder}")
            return "OK", []

        def logout(self):
            calls.append("imap:logout")

    monkeypatch.setattr("app.services.communications._ensure_public_mail_host", lambda host: None)
    monkeypatch.setattr("app.services.communications.smtplib.SMTP", FakeSmtp)
    monkeypatch.setattr("app.services.communications.imaplib.IMAP4_SSL", FakeImap)
    result = _test_smtp_imap(
        {
            "from_address": "teacher@example.test",
            "smtp_host": "smtp.example.test",
            "smtp_port": 587,
            "smtp_username": "teacher@example.test",
            "smtp_password": "secret",
            "smtp_starttls": True,
            "imap_host": "imap.example.test",
            "imap_port": 993,
            "imap_username": "teacher@example.test",
            "imap_password": "secret",
            "imap_ssl": True,
        }
    )
    assert result == {"smtp": "ok", "imap": "ok"}
    assert "smtp:starttls" in calls
    assert "imap:select:INBOX" in calls


def test_infobip_base_url_rejects_non_infobip_host() -> None:
    from pydantic import ValidationError

    from app.schemas.communications import InfobipConnectRequest

    try:
        InfobipConnectRequest(base_url="https://127.0.0.1", api_key="abcdefgh")
    except ValidationError:
        pass
    else:
        raise AssertionError("non-Infobip base URL must be rejected")


def test_mail_host_rejects_private_addresses(monkeypatch) -> None:
    import socket

    from app.services.communications import _ensure_public_mail_host

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))
        ],
    )
    try:
        _ensure_public_mail_host("mail.example.test")
    except ValueError as exc:
        assert "Private or local" in str(exc)
    else:
        raise AssertionError("private mail address must be rejected")


def test_ponto_pagination_url_rejects_foreign_host(monkeypatch) -> None:
    monkeypatch.setattr(
        ponto.settings,
        "ponto_connect_api_url",
        "https://api.ibanity.com/ponto-connect",
    )
    assert ponto._safe_api_url("accounts") == "https://api.ibanity.com/ponto-connect/accounts"
    try:
        ponto._safe_api_url("https://attacker.example/steal")
    except ValueError as exc:
        assert "unexpected pagination URL" in str(exc)
    else:
        raise AssertionError("foreign pagination URL must be rejected")


def test_platform_email_provider_is_explicit_and_legacy_compatible(monkeypatch) -> None:
    monkeypatch.setattr(settings, "smtp_host", "smtp.platform.example")
    monkeypatch.setattr(settings, "mail_from_address", "noreply@example.test")
    assert canonical_internal_provider("email", "smtp_imap", {}) == "zahlmeister_email"
    assert canonical_internal_provider(
        "email", "smtp_imap", {"smtp_host": "smtp.customer.example"}
    ) == "smtp_imap"
    assert internal_channel_configured(
        "email", provider="zahlmeister_email", config={}
    )


def test_legacy_empty_smtp_payload_is_stored_as_platform_provider() -> None:
    payload = ChannelSettingUpdate(mode="internal", provider="smtp_imap", fields={})
    assert payload.provider == "zahlmeister_email"


def test_microsoft365_oauth_state_roundtrip() -> None:
    state = microsoft365._state(
        "33333333-3333-3333-3333-333333333333",
        "44444444-4444-4444-4444-444444444444",
    )
    assert microsoft365.verify_state(state) == (
        "33333333-3333-3333-3333-333333333333",
        "44444444-4444-4444-4444-444444444444",
    )


def test_microsoft365_authorization_uses_pkce_and_minimal_mail_scopes(monkeypatch) -> None:
    monkeypatch.setattr(microsoft365.settings, "microsoft365_client_id", "client-id")
    monkeypatch.setattr(microsoft365.settings, "microsoft365_client_secret", "client-secret")
    monkeypatch.setattr(microsoft365.settings, "microsoft365_tenant", "organizations")
    monkeypatch.setattr(
        microsoft365.settings,
        "microsoft365_scopes",
        "openid profile offline_access User.Read Mail.Read Mail.Send",
    )
    monkeypatch.setattr(microsoft365.settings, "oauth_callback_base_url", "http://localhost:8003")
    connection = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333",
        encrypted_config=None,
    )
    url = microsoft365.authorization_url(
        connection,
        "44444444-4444-4444-4444-444444444444",
    )
    assert url.startswith("https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?")
    assert "code_challenge_method=S256" in url
    assert "client_id=client-id" in url
    assert "Mail.Read" in url
    assert "Mail.Send" in url
    assert "Mail.ReadWrite" not in url
    assert connection.encrypted_config


def test_microsoft365_is_valid_internal_email_provider() -> None:
    assert internal_channel_configured(
        "email",
        provider="microsoft365",
        connection_active=True,
    )
    assert not internal_channel_configured(
        "sms",
        provider="microsoft365",
        connection_active=True,
    )


@pytest.mark.asyncio
async def test_microsoft365_sendmail_uses_mime_message_id(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_mailbox(_connection_id):
        return "teacher@example.test"

    async def fake_graph(connection_id, method, path, **kwargs):
        calls.append(
            {
                "connection_id": connection_id,
                "method": method,
                "path": path,
                "headers": kwargs.get("headers") or {},
                "content": kwargs.get("content") or b"",
            }
        )
        return SimpleNamespace(status_code=202)

    monkeypatch.setattr(microsoft365, "_mailbox_address", fake_mailbox)
    monkeypatch.setattr(microsoft365, "_graph", fake_graph)
    content = CanonicalMessage(
        subject="Schulausflug",
        text="Bitte bezahlen.",
        payment_link_included=False,
        payment_qr_requested=False,
        transport_key="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    external_id = await microsoft365.send_email(
        connection_id="connection-1",
        recipient="parent@example.test",
        content=content,
    )
    assert external_id == "<zm-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee@zahlmeister>"
    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/me/sendMail"
    assert calls[0]["headers"]["Content-Type"] == "text/plain"
    decoded = base64.b64decode(calls[0]["content"]).decode("utf-8")
    assert "Message-ID: <zm-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee@zahlmeister>" in decoded
    assert "Subject: Schulausflug" in decoded


@pytest.mark.asyncio
async def test_microsoft365_inbox_parses_reply_metadata(monkeypatch) -> None:
    class FakeResponse:
        def json(self):
            return {
                "value": [
                    {
                        "id": "immutable-1",
                        "conversationId": "conversation-1",
                        "internetMessageId": "<incoming@example.test>",
                        "receivedDateTime": "2026-09-07T12:00:00Z",
                        "subject": "Re: Schulausflug",
                        "from": {"emailAddress": {"address": "parent@example.test"}},
                        "toRecipients": [
                            {"emailAddress": {"address": "teacher@example.test"}}
                        ],
                        "body": {"contentType": "text", "content": "Ist überwiesen."},
                        "internetMessageHeaders": [
                            {"name": "In-Reply-To", "value": "<outgoing@example.test>"},
                            {"name": "References", "value": "<older@example.test> <outgoing@example.test>"},
                        ],
                    }
                ]
            }

    async def fake_graph(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(microsoft365, "_graph", fake_graph)
    rows, cursor = await microsoft365.fetch_inbox(
        "33333333-3333-3333-3333-333333333333",
        "2026-09-07T11:55:00Z",
    )
    assert len(rows) == 1
    assert rows[0].conversation_id == "conversation-1"
    assert rows[0].in_reply_to == "<outgoing@example.test>"
    assert rows[0].references[-1] == "<outgoing@example.test>"
    assert rows[0].sender == "parent@example.test"
    assert rows[0].text == "Ist überwiesen."
    assert cursor == "2026-09-07T12:00:00Z"
