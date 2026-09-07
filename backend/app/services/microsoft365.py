from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import CommunicationConnection
from app.services.message_renderer import CanonicalMessage
from app.services.payments import render_qr_png
from app.services.secrets import decrypt_config, encrypt_config


@dataclass(frozen=True)
class MicrosoftMail:
    external_id: str
    conversation_id: str | None
    in_reply_to: str | None
    references: tuple[str, ...]
    sender: str | None
    recipient: str | None
    subject: str | None
    text: str
    received_at: datetime


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _state(connection_id: str, organization_id: str, ttl_seconds: int = 600) -> str:
    payload = json.dumps(
        {
            "connection_id": connection_id,
            "organization_id": organization_id,
            "exp": int(time.time()) + ttl_seconds,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    body = _b64url(payload)
    signature = _b64url(
        hmac.new(settings.app_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def verify_state(value: str) -> tuple[str, str]:
    try:
        body, signature = value.split(".", 1)
        expected = _b64url(
            hmac.new(
                settings.app_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid Microsoft OAuth state")
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("Expired Microsoft OAuth state")
        return str(payload["connection_id"]), str(payload["organization_id"])
    except Exception as exc:
        if isinstance(exc, ValueError) and "Microsoft OAuth state" in str(exc):
            raise
        raise ValueError("Invalid Microsoft OAuth state") from exc


def redirect_uri() -> str:
    return f"{settings.oauth_callback_base}/api/v1/communication-settings/microsoft365/oauth/callback"


def configured() -> bool:
    return bool(
        settings.microsoft365_client_id.strip()
        and settings.microsoft365_client_secret.strip()
        and settings.microsoft365_tenant.strip()
    )


def authorization_url(connection: CommunicationConnection, organization_id: str) -> str:
    if not configured():
        raise ValueError("Microsoft 365 is not configured for this Zahlmeister installation")
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    config = decrypt_config(connection.encrypted_config)
    config.update({"pkce_verifier": verifier, "oauth_started_at": time.time()})
    connection.encrypted_config = encrypt_config(config)
    query = urlencode(
        {
            "client_id": settings.microsoft365_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri(),
            "response_mode": "query",
            "scope": settings.microsoft365_scopes,
            "state": _state(str(connection.id), organization_id),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    tenant = settings.microsoft365_tenant.strip()
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{query}"


async def exchange_code(connection: CommunicationConnection, code: str) -> dict[str, Any]:
    config = decrypt_config(connection.encrypted_config)
    verifier = str(config.get("pkce_verifier") or "")
    if not verifier:
        raise ValueError("Microsoft OAuth PKCE verifier is missing")
    tenant = settings.microsoft365_tenant.strip()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "client_id": settings.microsoft365_client_id,
                "client_secret": settings.microsoft365_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(),
                "scope": settings.microsoft365_scopes,
                "code_verifier": verifier,
            },
        )
    if response.status_code >= 400:
        raise ValueError(_oauth_error(response))
    payload = response.json()
    if not payload.get("access_token"):
        raise ValueError("Microsoft token response did not contain an access token")
    config.update(_token_config(payload))
    config.pop("pkce_verifier", None)
    config.pop("oauth_started_at", None)
    connection.encrypted_config = encrypt_config(config)
    return payload


def _oauth_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        description = str(payload.get("error_description") or payload.get("error") or "").strip()
    except Exception:
        description = ""
    return description[:1000] or f"Microsoft OAuth failed with HTTP {response.status_code}"


def _token_config(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in") or 3600) - 60,
        "scope": payload.get("scope"),
    }


async def _access_token(connection_id) -> str:
    async with SessionLocal.begin() as session:
        connection = await session.get(CommunicationConnection, connection_id, with_for_update=True)
        if connection is None or connection.provider != "microsoft365":
            raise ValueError("Microsoft 365 connection does not exist")
        config = decrypt_config(connection.encrypted_config)
        token = str(config.get("access_token") or "")
        if token and float(config.get("expires_at") or 0) > time.time():
            return token
        refresh_token = str(config.get("refresh_token") or "")
        if not refresh_token:
            raise ValueError("Microsoft 365 authorization expired; reconnect the mailbox")
        tenant = settings.microsoft365_tenant.strip()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "client_id": settings.microsoft365_client_id,
                    "client_secret": settings.microsoft365_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": settings.microsoft365_scopes,
                },
            )
        if response.status_code >= 400:
            connection.status = "error"
            connection.last_error = _oauth_error(response)
            raise ValueError(connection.last_error)
        payload = response.json()
        config.update(_token_config(payload))
        if not payload.get("refresh_token"):
            config["refresh_token"] = refresh_token
        connection.encrypted_config = encrypt_config(config)
        connection.status = "connected"
        connection.last_error = None
        return str(payload["access_token"])


async def _graph(connection_id, method: str, path: str, **kwargs) -> httpx.Response:
    token = await _access_token(connection_id)
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"Bearer {token}"
    headers.setdefault("Accept", "application/json")
    url = f"{settings.microsoft365_graph_url.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(method, url, headers=headers, **kwargs)
    if response.status_code == 401:
        raise ValueError("Microsoft 365 authorization is no longer valid; reconnect the mailbox")
    if response.status_code >= 400:
        try:
            payload = response.json()
            message = str(payload.get("error", {}).get("message") or "")
        except Exception:
            message = ""
        raise ValueError(message[:1000] or f"Microsoft Graph returned HTTP {response.status_code}")
    return response


async def profile(connection_id) -> dict[str, Any]:
    response = await _graph(
        connection_id,
        "GET",
        "/me?$select=id,displayName,mail,userPrincipalName",
    )
    return response.json()


async def test_connection(connection_id) -> dict[str, str]:
    me = await profile(connection_id)
    await _graph(connection_id, "GET", "/me/mailFolders/inbox?$select=id,displayName")
    return {
        "mailbox": str(me.get("mail") or me.get("userPrincipalName") or ""),
        "display_name": str(me.get("displayName") or ""),
    }


async def _mailbox_address(connection_id) -> str:
    async with SessionLocal() as session:
        connection = await session.get(CommunicationConnection, connection_id)
        if connection is None or connection.provider != "microsoft365":
            raise ValueError("Microsoft 365 connection does not exist")
        label = str(connection.account_label or "").strip()
    if "@" in label and "\r" not in label and "\n" not in label:
        return label
    me = await profile(connection_id)
    mailbox = str(me.get("mail") or me.get("userPrincipalName") or "").strip()
    if "@" not in mailbox or "\r" in mailbox or "\n" in mailbox:
        raise ValueError("Microsoft 365 mailbox address is unavailable")
    return mailbox


async def send_email(
    *,
    connection_id,
    recipient: str,
    content: CanonicalMessage,
) -> str:
    """Send through Graph sendMail with a stable RFC Message-ID for reply correlation."""
    sender = await _mailbox_address(connection_id)
    transport_key = content.transport_key or secrets.token_hex(16)
    message_id = f"<zm-{transport_key}@zahlmeister>"
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = content.subject or ""
    message["Message-ID"] = message_id
    message.set_content(content.text)
    if content.payment_qr_payload:
        message.add_attachment(
            render_qr_png(content.payment_qr_payload),
            maintype="image",
            subtype="png",
            filename="zahlmeister-payment-qr.png",
        )
    encoded = base64.b64encode(message.as_bytes()).decode("ascii")
    await _graph(
        connection_id,
        "POST",
        "/me/sendMail",
        headers={"Content-Type": "text/plain"},
        content=encoded.encode("ascii"),
    )
    return message_id


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


def _address(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    email = value.get("emailAddress")
    if not isinstance(email, dict):
        return None
    address = str(email.get("address") or "").strip()
    return address or None


def _headers(message: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in message.get("internetMessageHeaders") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().casefold()
        value = str(item.get("value") or "").strip()
        if name and value:
            result[name] = value
    return result


async def fetch_inbox(connection_id, cursor: str | None) -> tuple[list[MicrosoftMail], str]:
    if cursor:
        try:
            since = datetime.fromisoformat(cursor.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            since = datetime.now(UTC) - timedelta(minutes=10)
    else:
        since = datetime.now(UTC) - timedelta(minutes=10)
    # Small overlap protects against delivery/order timing. Duplicates are removed by external_id.
    query_since = since - timedelta(minutes=2)
    filter_value = query_since.isoformat().replace("+00:00", "Z")
    path = (
        "/me/mailFolders/inbox/messages"
        "?$top=100&$orderby=receivedDateTime%20desc"
        "&$select=id,conversationId,internetMessageId,receivedDateTime,subject,from,toRecipients,body,internetMessageHeaders"
        f"&$filter=receivedDateTime%20ge%20{filter_value}"
    )
    response = await _graph(
        connection_id,
        "GET",
        path,
        headers={"Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"'},
    )
    rows = response.json().get("value") or []
    result: list[MicrosoftMail] = []
    newest = since
    for item in rows:
        if not isinstance(item, dict):
            continue
        received = _parse_datetime(str(item.get("receivedDateTime") or ""))
        newest = max(newest, received)
        headers = _headers(item)
        references = tuple(
            part for part in str(headers.get("references") or "").split() if part
        )
        body = item.get("body") or {}
        to_recipients = item.get("toRecipients") or []
        result.append(
            MicrosoftMail(
                external_id=str(item.get("internetMessageId") or item.get("id") or ""),
                conversation_id=str(item.get("conversationId") or "") or None,
                in_reply_to=headers.get("in-reply-to"),
                references=references,
                sender=_address(item.get("from")),
                recipient=_address(to_recipients[0]) if to_recipients else None,
                subject=str(item.get("subject") or "").strip() or None,
                text=str(body.get("content") or "").strip(),
                received_at=received,
            )
        )
    return result, newest.isoformat().replace("+00:00", "Z")
