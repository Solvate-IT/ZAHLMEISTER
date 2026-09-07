from __future__ import annotations

import base64
import hashlib
import hmac
from email.utils import parseaddr
from uuid import UUID

from app.core.config import settings


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _reply_domain() -> str:
    configured = settings.mail_reply_domain.strip().lower()
    if configured:
        return configured
    address = parseaddr(settings.mail_from_address)[1]
    if "@" not in address:
        raise ValueError("MAIL_REPLY_DOMAIN or a valid MAIL_FROM_ADDRESS is required")
    return address.rsplit("@", 1)[1].lower()


def reply_token(message_id: UUID) -> str:
    body = _b64url(message_id.bytes)
    signature = _b64url(
        hmac.new(
            settings.app_secret.encode("utf-8"),
            f"central-mail:{body}".encode("ascii"),
            hashlib.sha256,
        ).digest()[:16]
    )
    return f"{body}.{signature}"


def reply_address(message_id: UUID) -> str:
    return f"reply+{reply_token(message_id)}@{_reply_domain()}"


def message_id_from_reply_address(value: str | None) -> UUID | None:
    address = parseaddr(value or "")[1].strip().lower()
    if not address or "@" not in address:
        return None
    local, domain = address.rsplit("@", 1)
    if domain != _reply_domain() or not local.startswith("reply+"):
        return None
    token = local[6:]
    try:
        body, signature = token.split(".", 1)
        expected = _b64url(
            hmac.new(
                settings.app_secret.encode("utf-8"),
                f"central-mail:{body}".encode("ascii"),
                hashlib.sha256,
            ).digest()[:16]
        )
        if not hmac.compare_digest(signature, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(raw) != 16:
            return None
        return UUID(bytes=raw)
    except (ValueError, TypeError):
        return None


def platform_imap_config() -> dict[str, object]:
    return {
        "imap_host": settings.platform_imap_host,
        "imap_port": settings.platform_imap_port,
        "imap_username": settings.platform_imap_username,
        "imap_password": settings.platform_imap_password,
        "imap_ssl": settings.platform_imap_ssl,
        "imap_starttls": settings.platform_imap_starttls,
        "imap_folder": settings.platform_imap_folder,
    }


def platform_inbox_configured() -> bool:
    return bool(
        settings.platform_imap_host.strip()
        and settings.platform_imap_username.strip()
        and settings.platform_imap_password
    )
