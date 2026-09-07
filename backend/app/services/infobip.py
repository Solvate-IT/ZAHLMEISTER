import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import CommunicationConnection
from app.services.message_renderer import CanonicalMessage
from app.services.payments import render_qr_png
from app.services.secrets import decrypt_config, encrypt_config

INFOBIP_MESSAGES_CHANNELS = {
    "sms": "SMS",
    "whatsapp": "WHATSAPP",
}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sign_oauth_state(organization_id: str, ttl_seconds: int = 600) -> str:
    payload = json.dumps(
        {"organization_id": organization_id, "exp": int(time.time()) + ttl_seconds},
        separators=(",", ":"),
    ).encode("utf-8")
    body = _b64url(payload)
    signature = _b64url(
        hmac.new(settings.app_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def verify_oauth_state(value: str) -> str:
    try:
        body, signature = value.split(".", 1)
        expected = _b64url(
            hmac.new(
                settings.app_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid OAuth state")
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("Expired OAuth state")
        organization_id = str(payload.get("organization_id") or "")
        if not organization_id:
            raise ValueError("Invalid OAuth state")
        return organization_id
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValueError) and str(exc) in {
            "Invalid OAuth state",
            "Expired OAuth state",
        }:
            raise
        raise ValueError("Invalid OAuth state") from exc


def oauth_redirect_uri() -> str:
    return f"{settings.oauth_callback_base}/api/v1/communication-settings/infobip/oauth/callback"


def oauth_authorization_url(organization_id: str) -> str:
    if not settings.infobip_oauth_client_id:
        raise ValueError("Infobip OAuth is not configured for this Zahlmeister installation")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.infobip_oauth_client_id,
            "state": sign_oauth_state(organization_id),
            "redirect_uri": oauth_redirect_uri(),
            "scope": settings.infobip_oauth_scopes,
        }
    )
    return f"{settings.infobip_oauth_authorize_url}?{query}"


async def exchange_oauth_code(code: str) -> dict[str, Any]:
    data = {
        "client_id": settings.infobip_oauth_client_id,
        "client_secret": settings.infobip_oauth_client_secret,
        "code": code,
        "redirect_uri": oauth_redirect_uri(),
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.infobip_oauth_token_url,
            data=data,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    token = str(payload.get("token") or "")
    if not token:
        raise ValueError("Infobip OAuth response did not contain a token")
    return payload


async def refresh_oauth_token(config: dict[str, Any]) -> dict[str, Any]:
    token = str(config.get("token") or "")
    if not token:
        raise ValueError("Infobip OAuth token missing")
    data = {
        "client_id": settings.infobip_oauth_client_id,
        "client_secret": settings.infobip_oauth_client_secret,
        "code": token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.infobip_oauth_token_url,
            data=data,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    refreshed = str(payload.get("token") or "")
    if not refreshed:
        raise ValueError("Infobip OAuth refresh did not contain a token")
    return payload


async def authorization_for_connection(
    session: AsyncSession, connection: CommunicationConnection
) -> tuple[str, str]:
    config = decrypt_config(connection.encrypted_config)
    base_url = str(config.get("base_url") or settings.infobip_default_base_url).rstrip("/")
    if connection.auth_type == "api_key":
        api_key = str(config.get("api_key") or "")
        if not api_key:
            raise ValueError("Infobip API key missing")
        return f"App {api_key}", base_url

    if connection.auth_type != "oauth":
        raise ValueError(f"Unsupported Infobip auth type: {connection.auth_type}")

    obtained_at = float(config.get("obtained_at") or 0)
    if time.time() - obtained_at > 40:
        payload = await refresh_oauth_token(config)
        config.update(
            {
                "token": payload["token"],
                "token_type": payload.get("tokenType") or "IBSSO",
                "obtained_at": time.time(),
                "base_url": base_url,
            }
        )
        connection.encrypted_config = encrypt_config(config)
        connection.last_error = None
        await session.flush()

    token = str(config.get("token") or "")
    token_type = str(config.get("token_type") or "IBSSO")
    if not token:
        raise ValueError("Infobip OAuth token missing")
    return f"{token_type} {token}", base_url


async def validate_api_key(base_url: str, api_key: str) -> None:
    url = f"{base_url.rstrip('/')}/account/1/balance"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers={"Authorization": f"App {api_key}"})
    if response.status_code in {401, 403}:
        raise ValueError("Infobip API key is not authorized")
    if response.status_code >= 500:
        raise ValueError("Infobip is currently unavailable")
    if response.status_code >= 400:
        raise ValueError(f"Infobip connection test failed ({response.status_code})")


async def send_infobip_message(
    *,
    authorization: str,
    base_url: str,
    channel: str,
    sender: str,
    recipient: str,
    content: CanonicalMessage,
    callback_data: str,
    webhook_url: str | None,
) -> str:
    headers = {"Authorization": authorization, "Accept": "application/json"}

    if channel == "email":
        data = {
            "from": sender,
            "to": recipient,
            "subject": content.subject,
            "text": content.text,
        }
        data["header"] = f"X-Zahlmeister-Message-ID: {callback_data}"
        files = None
        if content.payment_qr_payload:
            image_bytes = await asyncio.to_thread(render_qr_png, content.payment_qr_payload)
            files = {"attachment": ("zahlmeister-payment-qr.png", image_bytes, "image/png")}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{base_url}/email/3/send",
                headers=headers,
                data=data,
                files=files,
            )
            response.raise_for_status()
            payload = response.json()
        messages = payload.get("messages") or []
        if messages and isinstance(messages[0], dict):
            return str(messages[0].get("messageId") or messages[0].get("messageID") or callback_data)
        return str(payload.get("messageId") or payload.get("messageID") or callback_data)

    if channel == "telegram":
        raise ValueError(
            "Telegram cannot be used by Infobip to initiate a new conversation; "
            "the recipient must contact the configured Telegram channel first"
        )

    api_channel = INFOBIP_MESSAGES_CHANNELS.get(channel)
    if not api_channel:
        raise ValueError(f"Infobip internal sending is not implemented for channel: {channel}")

    body: dict[str, Any]
    if content.payment_qr_url:
        body = {"type": "IMAGE", "url": content.payment_qr_url, "text": content.text}
    else:
        body = {"text": content.text, "type": "TEXT"}
    message: dict[str, Any] = {
        "channel": api_channel,
        "sender": sender,
        "destinations": [{"to": recipient}],
        "content": {"body": body},
        "callbackData": callback_data,
    }
    if content.payment_qr_url:
        message["options"] = {"adaptationMode": True}
    if webhook_url:
        message["webhooks"] = {
            "delivery": {"url": webhook_url},
            "seen": {"url": webhook_url},
        }
    payload = {"messages": [message]}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{base_url}/messages-api/1/messages",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    messages = data.get("messages") or []
    if messages and isinstance(messages[0], dict):
        return str(
            messages[0].get("messageId")
            or messages[0].get("messageID")
            or messages[0].get("id")
            or callback_data
        )
    return str(data.get("messageId") or data.get("messageID") or callback_data)


def connection_webhook_url(webhook_key: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/api/v1/webhooks/infobip/{webhook_key}"


def oauth_connection_config(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": str(payload.get("token") or ""),
        "token_type": str(payload.get("tokenType") or "IBSSO"),
        "obtained_at": time.time(),
        "base_url": settings.infobip_default_base_url.rstrip("/"),
        "locale": payload.get("locale"),
        "username": payload.get("username"),
        "email": payload.get("email"),
    }


def connection_is_active(connection: CommunicationConnection | None) -> bool:
    return connection is not None and connection.status == "connected"


async def test_connection(session: AsyncSession, connection: CommunicationConnection) -> None:
    authorization, base_url = await authorization_for_connection(session, connection)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{base_url.rstrip('/')}/account/1/balance",
            headers={"Authorization": authorization, "Accept": "application/json"},
        )
    if response.status_code in {401, 403}:
        raise ValueError("Infobip credentials or API scopes are not authorized")
    if response.status_code >= 500:
        raise ValueError("Infobip is currently unavailable")
    if response.status_code >= 400:
        raise ValueError(f"Infobip connection test failed ({response.status_code})")
