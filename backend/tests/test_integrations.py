from __future__ import annotations

from decimal import Decimal

from app.services import ponto
from app.services.bank_sync import parse_ponto_account, parse_ponto_transaction
from app.services.bank_sync_providers import get_bank_sync_provider
from app.services.communications import _test_smtp_imap


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
    state = ponto.sign_state("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    assert ponto.verify_state(state) == (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )


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
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))],
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
