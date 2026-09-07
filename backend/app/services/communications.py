import asyncio
import imaplib
import ipaddress
import re
import smtplib
import socket
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from typing import Any
from urllib.parse import quote, urlencode

from app.core.config import settings
from app.services.message_renderer import CanonicalMessage
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
    if not value:
        return ""
    value = value.strip()
    prefix = "+" if value.startswith("+") else ""
    digits = "".join(char for char in value if char.isdigit())
    return f"{prefix}{digits}" if digits else ""


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
        digits = "".join(char for char in recipient if char.isdigit())
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


def _smtp_send(
    recipient: str,
    content: CanonicalMessage,
    config: dict[str, Any],
    message_id: str,
) -> None:
    config = _effective_smtp_config(config)
    host = str(config.get("smtp_host") or "").strip()
    port = int(config.get("smtp_port") or (465 if config.get("smtp_ssl") else 587))
    username = str(config.get("smtp_username") or "").strip()
    password = str(config.get("smtp_password") or "")
    from_address = str(config.get("from_address") or username).strip()
    from_name = str(config.get("from_name") or "Zahlmeister").strip()
    reply_to = str(config.get("reply_to") or "").strip()
    if not host or not from_address:
        raise ValueError("SMTP host and sender address are required")
    _ensure_public_mail_host(host)

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

    smtp_ssl = bool(config.get("smtp_ssl", False))
    starttls = bool(config.get("smtp_starttls", not smtp_ssl))
    client_cls = smtplib.SMTP_SSL if smtp_ssl else smtplib.SMTP
    with client_cls(host, port, timeout=30) as client:
        if starttls and not smtp_ssl:
            client.starttls()
        if username:
            client.login(username, password)
        client.send_message(message)


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
    client = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    try:
        if not use_ssl and bool(config.get("imap_starttls", True)):
            client.starttls()
        client.login(username, password)
        client.select(str(config.get("imap_folder") or "INBOX"), readonly=True)
        typ, data = client.uid("search", None, "ALL")
        if typ != "OK" or not data:
            return []
        uids = [
            int(item)
            for item in data[0].split()
            if item.isdigit() and int(item) > last_uid
        ]
        result: list[IncomingMail] = []
        for uid in uids[-250:]:
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
    smtp_host = str(config.get("smtp_host") or "").strip()
    from_address = str(config.get("from_address") or "").strip()
    if not smtp_host or not from_address:
        raise ValueError("SMTP host and sender address are required")
    _ensure_public_mail_host(smtp_host)
    smtp_ssl = bool(config.get("smtp_ssl", False))
    smtp_port = int(config.get("smtp_port") or (465 if smtp_ssl else 587))
    smtp_cls = smtplib.SMTP_SSL if smtp_ssl else smtplib.SMTP
    with smtp_cls(smtp_host, smtp_port, timeout=20) as client:
        if bool(config.get("smtp_starttls", not smtp_ssl)) and not smtp_ssl:
            client.starttls()
        username = str(config.get("smtp_username") or "").strip()
        if username:
            client.login(username, str(config.get("smtp_password") or ""))
        client.noop()
    result["smtp"] = "ok"

    imap_host = str(config.get("imap_host") or "").strip()
    if imap_host:
        _ensure_public_mail_host(imap_host)
        imap_ssl = bool(config.get("imap_ssl", True))
        imap_port = int(config.get("imap_port") or (993 if imap_ssl else 143))
        imap = (
            imaplib.IMAP4_SSL(imap_host, imap_port)
            if imap_ssl
            else imaplib.IMAP4(imap_host, imap_port)
        )
        try:
            if not imap_ssl and bool(config.get("imap_starttls", True)):
                imap.starttls()
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
