"""Mail transport: pooled SMTP connections and incremental IMAP reads."""
import ssl
from types import SimpleNamespace

import pytest

from app.services import communications
from app.services.communications import SmtpConnectionPool, _imap_uids_to_fetch, _smtp_send


class FakeSmtp:
    opened: list[FakeSmtp] = []

    def __init__(self, host, port, timeout):
        self.sent: list = []
        self.closed = False
        self.noop_code = 250
        self.context = None
        FakeSmtp.opened.append(self)

    def starttls(self, context=None):
        self.context = context

    def login(self, username, password):
        pass

    def noop(self):
        return self.noop_code, b"ok"

    def send_message(self, message):
        self.sent.append(message["Message-ID"])

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


def _content():
    return SimpleNamespace(subject="Ausflug", text="Hallo", payment_qr_payload=None)


CONFIG = {
    "smtp_host": "smtp.example.test",
    "smtp_port": 587,
    "smtp_username": "verein@example.test",
    "smtp_password": "secret",
    "smtp_starttls": True,
    "from_address": "verein@example.test",
}


@pytest.fixture(autouse=True)
def isolated_pool(monkeypatch):
    FakeSmtp.opened = []
    monkeypatch.setattr(communications, "SMTP_POOL", SmtpConnectionPool())
    monkeypatch.setattr(communications, "_ensure_public_mail_host", lambda host: None)
    monkeypatch.setattr(communications.smtplib, "SMTP", FakeSmtp)


def test_bulk_deliveries_reuse_one_verified_connection() -> None:
    for number in range(3):
        _smtp_send("ben@example.test", _content(), CONFIG, f"<zm-{number}@zahlmeister>")
    assert len(FakeSmtp.opened) == 1
    connection = FakeSmtp.opened[0]
    assert connection.sent == ["<zm-0@zahlmeister>", "<zm-1@zahlmeister>", "<zm-2@zahlmeister>"]
    assert connection.context.verify_mode == ssl.CERT_REQUIRED


def test_dead_pooled_connection_is_replaced() -> None:
    _smtp_send("ben@example.test", _content(), CONFIG, "<zm-1@zahlmeister>")
    FakeSmtp.opened[0].noop_code = 421
    _smtp_send("ben@example.test", _content(), CONFIG, "<zm-2@zahlmeister>")
    assert len(FakeSmtp.opened) == 2
    assert FakeSmtp.opened[0].closed
    assert FakeSmtp.opened[1].sent == ["<zm-2@zahlmeister>"]


def test_failed_delivery_never_returns_its_connection_to_the_pool() -> None:
    def refuse(message):
        raise communications.smtplib.SMTPServerDisconnected("gone")

    _smtp_send("ben@example.test", _content(), CONFIG, "<zm-1@zahlmeister>")
    FakeSmtp.opened[0].send_message = refuse
    with pytest.raises(communications.smtplib.SMTPServerDisconnected):
        _smtp_send("ben@example.test", _content(), CONFIG, "<zm-2@zahlmeister>")
    assert FakeSmtp.opened[0].closed
    _smtp_send("ben@example.test", _content(), CONFIG, "<zm-3@zahlmeister>")
    assert len(FakeSmtp.opened) == 2


def test_different_credentials_never_share_a_connection() -> None:
    _smtp_send("ben@example.test", _content(), CONFIG, "<zm-1@zahlmeister>")
    _smtp_send("ben@example.test", _content(), {**CONFIG, "smtp_password": "rotated"}, "<zm-2@zahlmeister>")
    assert len(FakeSmtp.opened) == 2


def test_imap_reads_oldest_first_and_never_skips_a_backlog() -> None:
    backlog = list(range(101, 701))
    first = _imap_uids_to_fetch(backlog, 100)
    assert first == list(range(101, 351))
    # The next round continues exactly where the cursor stopped.
    assert _imap_uids_to_fetch(backlog, max(first))[0] == 351
    # IMAP's "n:*" also returns the newest UID when there is nothing newer.
    assert _imap_uids_to_fetch([700], 700) == []


def test_first_imap_sync_starts_at_the_newest_messages() -> None:
    assert _imap_uids_to_fetch(list(range(1, 1001)), 0) == list(range(751, 1001))
