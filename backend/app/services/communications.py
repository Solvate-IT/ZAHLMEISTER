import asyncio
import hashlib
import imaplib
import ipaddress
import re
import smtplib
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from typing import Any
from urllib.parse import quote, urlencode

from app.core.config import settings
from app.services.message_renderer import CanonicalMessage
from app.services.phone_numbers import normalize_phone_number
from app.services.payments import render_qr_png


@dataclass(frozen=True)
class IncomingMail:
    uid: int
    message_id: str | None
    in_reply_to: str | None
    references: tuple[str, ...]
    sender: str | None
    recipient: str | None
    subject: str | None
    text: str


def normalize_phone(value: str | None) -> str:
    try:
        return normalize_phone_number(value) or ""
    except ValueError:
        # Some providers return international digits without the leading +.
        digits = "".join(char for char in (value or "") if char.isdigit())
        if value and not value.strip().startswith(("+", "0")) and len(digits) >= 10:
            try:
                return normalize_phone_number(f"+{digits}") or ""
            except ValueError:
                pass
        return ""


def external_launch_uri(
    channel: str,
    recipient: str | None,
    subject: str | None,
    body: str,
) -> tuple[str, bool]:
    if channel == "email":
        if not recipient:
            raise ValueError("Email recipient missing")
        query = urlencode({"subject": subject or "", "body": body})
        return f"mailto:{quote(recipient)}?{query}", False
    if channel == "sms":
        if not recipient:
            raise ValueError("SMS recipient missing")
        return f"sms:{quote(recipient)}?body={quote(body)}", False
    if channel == "whatsapp":
        if not recipient:
            raise ValueError("WhatsApp recipient missing")
        normalized = normalize_phone(recipient)
        if not normalized:
            raise ValueError("WhatsApp recipient must include a valid country code")
        digits = normalized[1:]
        return f"https://wa.me/{digits}?text={quote(body)}", False
    if channel == "telegram":
        if not recipient:
            raise ValueError("Telegram recipient missing")
        username = recipient.lstrip("@").strip()
        if not username:
            raise ValueError("Telegram username missing")
        return f"https://t.me/{quote(username)}", False
    raise ValueError(f"Unsupported channel: {channel}")


def recipient_for_channel(
    channel: str,
    *,
    email: str | None,
    phone: str | None,
    channel_addresses: dict[str, str] | None = None,
) -> str | None:
    addresses = channel_addresses or {}
    if channel == "email":
        return email.strip() if email and email.strip() else None
    if channel in {"sms", "whatsapp"}:
        normalized = normalize_phone(phone)
        return normalized or None
    if channel == "telegram":
        value = str(addresses.get("telegram") or "").strip()
        return value or None
    return None


def _ensure_public_mail_host(host: str) -> None:
    value = host.strip().rstrip(".")
    if not value:
        raise ValueError("Mail server host is required")
    if settings.environment != "production" and value.casefold() == "mailpit":
        return
    if value.lower() == "localhost":
        raise ValueError("Private mail server addresses are not allowed")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(value, None, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError(f"Mail server cannot be resolved: {value}") from exc
    if not addresses:
        raise ValueError(f"Mail server cannot be resolved: {value}")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private or local mail server addresses are not allowed")


def _effective_smtp_config(config: dict[str, Any]) -> dict[str, Any]:
    tenant_transport_keys = {
        "smtp_host",
        "smtp_port",
        "smtp_username",
        "smtp_password",
        "smtp_starttls",
        "smtp_ssl",
        "from_address",
    }
    # A tenant SMTP configuration must never silently fall back to the central
    # Zahlmeister transport when it is incomplete or invalid. Only the explicit
    # platform path (which contributes presentation fields such as from_name and
    # reply_to, but no tenant transport fields) may use installation-level SMTP.
    if any(key in config for key in tenant_transport_keys):
        return config
    if not settings.smtp_host.strip() or not settings.mail_from_address.strip():
        return config
    return {
        **config,
        "smtp_host": settings.smtp_host,
        "smtp_port": settings.smtp_port,
        "smtp_username": settings.smtp_username,
        "smtp_password": settings.smtp_password,
        "smtp_starttls": settings.smtp_starttls,
        "smtp_ssl": False,
        "from_address": settings.mail_from_address,
        "from_name": config.get("from_name") or settings.mail_from_name,
    }


def tls_context() -> ssl.SSLContext:
    """Certificate- and hostname-verifying TLS for every mail server connection.

    smtplib and imaplib fall back to an unverified context when none is given,
    which would let anyone on the network path read mail passwords and messages.
    """
    return ssl.create_default_context()


@dataclass(frozen=True)
class _SmtpEndpoint:
    host: str
    port: int
    use_ssl: bool
    starttls: bool
    username: str
    password_digest: str


def _close_smtp(client: smtplib.SMTP) -> None:
    try:
        client.quit()
    except Exception:
        try:
            client.close()
        except Exception:
            pass


def _open_smtp(endpoint: _SmtpEndpoint, password: str, *, timeout: float = 30) -> smtplib.SMTP:
    context = tls_context()
    if endpoint.use_ssl:
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            endpoint.host, endpoint.port, timeout=timeout, context=context
        )
    else:
        client = smtplib.SMTP(endpoint.host, endpoint.port, timeout=timeout)
    try:
        if endpoint.starttls and not endpoint.use_ssl:
            client.starttls(context=context)
        if endpoint.username:
            client.login(endpoint.username, password)
    except Exception:
        _close_smtp(client)
        raise
    return client


class SmtpConnectionPool:
    """Authenticated SMTP connections kept for reuse across deliveries.

    A TLS handshake plus login costs more than sending one message, so bulk sends
    reuse a connection per endpoint (host, port, TLS mode, credentials). Deliveries
    run in threads (asyncio.to_thread), hence the lock. An idle connection is
    checked with NOOP before reuse and dropped after ``idle_seconds``.
    """

    def __init__(self, *, idle_seconds: float = 60.0, max_idle_per_endpoint: int = 4) -> None:
        self._idle_seconds = idle_seconds
        self._max_idle = max_idle_per_endpoint
        self._lock = threading.Lock()
        self._idle: dict[_SmtpEndpoint, list[tuple[smtplib.SMTP, float]]] = {}

    def acquire(self, endpoint: _SmtpEndpoint, password: str) -> smtplib.SMTP:
        while True:
            with self._lock:
                entries = self._idle.get(endpoint) or []
                entry = entries.pop() if entries else None
            if entry is None:
                return _open_smtp(endpoint, password)
            client, released_at = entry
            if time.monotonic() - released_at > self._idle_seconds:
                _close_smtp(client)
                continue
            try:
                code, _message = client.noop()
            except (smtplib.SMTPException, OSError):
                code = 0
            if code == 250:
                return client
            _close_smtp(client)

    def release(self, endpoint: _SmtpEndpoint, client: smtplib.SMTP) -> None:
        with self._lock:
            entries = self._idle.setdefault(endpoint, [])
            if len(entries) < self._max_idle:
                entries.append((client, time.monotonic()))
                return
        _close_smtp(client)

    def close_all(self) -> None:
        with self._lock:
            idle, self._idle = self._idle, {}
        for entries in idle.values():
            for client, _released_at in entries:
                _close_smtp(client)


SMTP_POOL = SmtpConnectionPool()


def _smtp_endpoint(config: dict[str, Any]) -> tuple[_SmtpEndpoint, str]:
    host = str(config.get("smtp_host") or "").strip()
    smtp_ssl = bool(config.get("smtp_ssl", False))
    port = int(config.get("smtp_port") or (465 if smtp_ssl else 587))
    username = str(config.get("smtp_username") or "").strip()
    password = str(config.get("smtp_password") or "")
    endpoint = _SmtpEndpoint(
        host=host,
        port=port,
        use_ssl=smtp_ssl,
        starttls=bool(config.get("smtp_starttls", not smtp_ssl)),
        username=username,
        password_digest=hashlib.sha256(password.encode("utf-8")).hexdigest(),
    )
    return endpoint, password


def _smtp_send(
    recipient: str,
    content: CanonicalMessage,
    config: dict[str, Any],
    message_id: str,
) -> None:
    config = _effective_smtp_config(config)
    endpoint, password = _smtp_endpoint(config)
    from_address = str(config.get("from_address") or endpoint.username).strip()
    from_name = str(config.get("from_name") or "Zahlmeister").strip()
    reply_to = str(config.get("reply_to") or "").strip()
    if not endpoint.host or not from_address:
        raise ValueError("SMTP host and sender address are required")
    _ensure_public_mail_host(endpoint.host)

    message = EmailMessage()
    message["Subject"] = content.subject or ""
    message["From"] = f"{from_name} <{from_address}>" if from_name else from_address
    message["To"] = recipient
    message["Message-ID"] = message_id
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(content.text)
    if content.payment_qr_payload:
        message.add_attachment(
            render_qr_png(content.payment_qr_payload),
            maintype="image",
            subtype="png",
            filename="zahlmeister-payment-qr.png",
        )

    client = SMTP_POOL.acquire(endpoint, password)
    try:
        client.send_message(message)
    except BaseException:
        # The connection's state is unknown after a failure; never reuse it.
        _close_smtp(client)
        raise
    SMTP_POOL.release(endpoint, client)


async def send_smtp_email(
    *, recipient: str, content: CanonicalMessage, config: dict[str, Any], message_id: str
) -> str:
    await asyncio.to_thread(_smtp_send, recipient, content, config, message_id)
    return message_id


def _extract_text(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                try:
                    return part.get_content().strip()
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    return payload.decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    ).strip()
        return ""
    try:
        return message.get_content().strip()
    except Exception:
        payload = message.get_payload(decode=True) or b""
        return payload.decode(
            message.get_content_charset() or "utf-8", errors="replace"
        ).strip()


def _open_imap(host: str, port: int, *, use_ssl: bool, starttls: bool) -> imaplib.IMAP4:
    context = tls_context()
    if use_ssl:
        return imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=_IMAP_TIMEOUT_SECONDS)
    client = imaplib.IMAP4(host, port, timeout=_IMAP_TIMEOUT_SECONDS)
    if starttls:
        try:
            client.starttls(ssl_context=context)
        except Exception:
            client.shutdown()
            raise
    return client


# Messages fetched per sync round. Rounds run every minute; a backlog is worked off
# over several rounds because the cursor only advances past what was read.
_IMAP_BATCH = 250
_IMAP_TIMEOUT_SECONDS = 30


def _imap_uids_to_fetch(found: list[int], last_uid: int) -> list[int]:
    uids = sorted(uid for uid in found if uid > last_uid)
    if last_uid == 0:
        # First sync of a mailbox: replies to Zahlmeister messages cannot predate the
        # connection, so start at the newest messages instead of the whole history.
        return uids[-_IMAP_BATCH:]
    return uids[:_IMAP_BATCH]


def _imap_fetch(config: dict[str, Any], last_uid: int) -> list[IncomingMail]:
    host = str(config.get("imap_host") or "").strip()
    port = int(config.get("imap_port") or (993 if config.get("imap_ssl", True) else 143))
    username = str(
        config.get("imap_username") or config.get("smtp_username") or ""
    ).strip()
    password = str(config.get("imap_password") or config.get("smtp_password") or "")
    if not host or not username:
        return []
    _ensure_public_mail_host(host)
    use_ssl = bool(config.get("imap_ssl", True))
    client = _open_imap(
        host,
        port,
        use_ssl=use_ssl,
        starttls=not use_ssl and bool(config.get("imap_starttls", True)),
    )
    try:
        client.login(username, password)
        client.select(str(config.get("imap_folder") or "INBOX"), readonly=True)
        # Only UIDs above the cursor. "n:*" also matches the highest existing UID
        # when n is larger, which the filter in _imap_uids_to_fetch removes again.
        typ, data = client.uid("search", None, f"UID {last_uid + 1}:*")
        if typ != "OK" or not data:
            return []
        found = [int(item) for item in data[0].split() if item.isdigit()]
        result: list[IncomingMail] = []
        for uid in _imap_uids_to_fetch(found, last_uid):
            typ, raw = client.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            message = BytesParser(policy=policy.default).parsebytes(raw[0][1])
            refs = tuple(re.findall(r"<[^>]+>", str(message.get("References") or "")))
            result.append(
                IncomingMail(
                    uid=uid,
                    message_id=str(message.get("Message-ID") or "").strip() or None,
                    in_reply_to=str(message.get("In-Reply-To") or "").strip() or None,
                    references=refs,
                    sender=parseaddr(str(message.get("From") or ""))[1] or None,
                    recipient=parseaddr(str(message.get("To") or ""))[1] or None,
                    subject=str(message.get("Subject") or "").strip() or None,
                    text=_extract_text(message),
                )
            )
        return result
    finally:
        try:
            client.logout()
        except Exception:
            pass


async def fetch_imap(config: dict[str, Any], last_uid: int) -> list[IncomingMail]:
    return await asyncio.to_thread(_imap_fetch, config, last_uid)


def _test_smtp_imap(config: dict[str, Any]) -> dict[str, str]:
    config = _effective_smtp_config(config)
    result: dict[str, str] = {}
    endpoint, password = _smtp_endpoint(config)
    from_address = str(config.get("from_address") or "").strip()
    if not endpoint.host or not from_address:
        raise ValueError("SMTP host and sender address are required")
    _ensure_public_mail_host(endpoint.host)
    client = _open_smtp(endpoint, password, timeout=20)
    try:
        client.noop()
    finally:
        _close_smtp(client)
    result["smtp"] = "ok"

    imap_host = str(config.get("imap_host") or "").strip()
    if imap_host:
        _ensure_public_mail_host(imap_host)
        imap_ssl = bool(config.get("imap_ssl", True))
        imap_port = int(config.get("imap_port") or (993 if imap_ssl else 143))
        imap = _open_imap(
            imap_host,
            imap_port,
            use_ssl=imap_ssl,
            starttls=not imap_ssl and bool(config.get("imap_starttls", True)),
        )
        try:
            username = str(
                config.get("imap_username") or config.get("smtp_username") or ""
            ).strip()
            if not username:
                raise ValueError("IMAP username is required")
            imap.login(
                username,
                str(config.get("imap_password") or config.get("smtp_password") or ""),
            )
            status, _ = imap.select(
                str(config.get("imap_folder") or "INBOX"), readonly=True
            )
            if status != "OK":
                raise ValueError("IMAP inbox cannot be opened")
            result["imap"] = "ok"
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    else:
        result["imap"] = "not_configured"
    return result


async def test_smtp_imap(config: dict[str, Any]) -> dict[str, str]:
    return await asyncio.to_thread(_test_smtp_imap, config)
