import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import quote, urlencode, urlparse

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
INFOBIP_WHATSAPP_TEMPLATE_NAME = "zahlmeister_payment_request"
INFOBIP_SUBSCRIPTION_EVENTS = {
    "sms": ["DELIVERY", "INBOUND_MESSAGE"],
    "whatsapp": ["DELIVERY", "SEEN", "INBOUND_MESSAGE"],
}
INFOBIP_WEBHOOK_USERNAME = "zahlmeister"


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


def _clean_base_url(value: object) -> str | None:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or (
        host != "api.infobip.com" and not host.endswith(".api.infobip.com")
    ):
        return None
    return raw


def _oauth_base_url(payload: dict[str, Any]) -> str:
    for key in ("baseUrl", "baseURL", "apiBaseUrl", "apiBaseURL"):
        value = _clean_base_url(payload.get(key))
        if value:
            return value
    return settings.infobip_default_base_url.rstrip("/")


async def authorization_for_connection(
    session: AsyncSession, connection: CommunicationConnection
) -> tuple[str, str]:
    config = decrypt_config(connection.encrypted_config)
    base_url = _clean_base_url(config.get("base_url")) or settings.infobip_default_base_url.rstrip("/")
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
        refreshed_base_url = _oauth_base_url(payload)
        if refreshed_base_url == settings.infobip_default_base_url.rstrip("/"):
            refreshed_base_url = base_url
        config.update(
            {
                "token": payload["token"],
                "token_type": payload.get("tokenType") or "IBSSO",
                "obtained_at": time.time(),
                "base_url": refreshed_base_url,
            }
        )
        connection.encrypted_config = encrypt_config(config)
        connection.last_error = None
        await session.flush()
        base_url = refreshed_base_url

    token = str(config.get("token") or "")
    token_type = str(config.get("token_type") or "IBSSO")
    if not token:
        raise ValueError("Infobip OAuth token missing")
    return f"{token_type} {token}", base_url


async def validate_api_key(base_url: str, api_key: str) -> None:
    cleaned = _clean_base_url(base_url)
    if cleaned is None:
        raise ValueError("Infobip base URL is invalid")
    url = f"{cleaned}/account/1/balance"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers={"Authorization": f"App {api_key}"})
    if response.status_code in {401, 403}:
        raise ValueError("Infobip API key is not authorized")
    if response.status_code >= 500:
        raise ValueError("Infobip is currently unavailable")
    if response.status_code >= 400:
        raise ValueError(f"Infobip connection test failed ({response.status_code})")


def connection_webhook_url(webhook_key: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/api/v1/webhooks/infobip/{webhook_key}"


def webhook_subscriptions_available() -> bool:
    parsed = urlparse(settings.public_app_url.strip())
    host = (parsed.hostname or "").lower()
    return bool(
        parsed.scheme == "https"
        and host
        and host not in {"localhost", "127.0.0.1", "::1"}
        and not host.endswith(".localhost")
    )


def _subscription_ids(connection: CommunicationConnection, channel: str) -> tuple[str, str, str]:
    suffix = f"{connection.id.hex[:20]}_{channel.lower()}"
    return (
        f"zm_{suffix}",
        f"zm_profile_{suffix}",
        f"zm_auth_{suffix}",
    )


def _subscription_marker(config: dict[str, Any], channel: str) -> dict[str, Any] | None:
    subscriptions = config.get("subscriptions")
    if not isinstance(subscriptions, dict):
        return None
    value = subscriptions.get(channel.lower())
    return value if isinstance(value, dict) else None


async def _subscription_request(
    method: str,
    url: str,
    authorization: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.request(
            method,
            url,
            headers={
                "Authorization": authorization,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=json_body,
        )


async def ensure_event_subscription(
    session: AsyncSession,
    connection: CommunicationConnection,
    channel: str,
    sender: str,
) -> bool:
    channel = channel.lower()
    sender = sender.strip()
    if channel not in INFOBIP_SUBSCRIPTION_EVENTS:
        return False
    if not sender:
        raise ValueError("Infobip sender/resource is required")
    if not webhook_subscriptions_available():
        return False
    if not connection.webhook_key:
        raise ValueError("Infobip webhook key is missing")

    authorization, base_url = await authorization_for_connection(session, connection)
    config = decrypt_config(connection.encrypted_config)
    marker = _subscription_marker(config, channel)
    subscription_id, profile_id, auth_id = _subscription_ids(connection, channel)
    endpoint = f"{base_url}/subscriptions/1/subscription/{channel.upper()}"

    if marker and marker.get("sender") == sender:
        stored_subscription_id = str(marker.get("subscription_id") or subscription_id)
        response = await _subscription_request(
            "GET",
            f"{endpoint}/{quote(stored_subscription_id, safe='')}",
            authorization,
        )
        if response.status_code == 200:
            return True
        if response.status_code != 404:
            response.raise_for_status()

    if marker:
        await remove_event_subscription(session, connection, channel)
        authorization, base_url = await authorization_for_connection(session, connection)
        config = decrypt_config(connection.encrypted_config)
        endpoint = f"{base_url}/subscriptions/1/subscription/{channel.upper()}"

    webhook_url = connection_webhook_url(connection.webhook_key)
    payload = {
        "subscriptionId": subscription_id,
        "name": f"Zahlmeister {channel.upper()} webhook",
        "events": INFOBIP_SUBSCRIPTION_EVENTS[channel],
        "resources": [sender],
        "profile": {
            "profileId": profile_id,
            "webhook": {"notifyUrl": webhook_url},
            "security": {
                "authId": auth_id,
                "type": "BASIC",
                "credentials": {
                    "username": INFOBIP_WEBHOOK_USERNAME,
                    "password": connection.webhook_key,
                },
            },
        },
    }
    response = await _subscription_request("POST", endpoint, authorization, json_body=payload)
    if response.status_code not in {200, 201}:
        if response.status_code == 409:
            raise ValueError(
                f"Infobip already has a conflicting {channel} webhook subscription for sender {sender}"
            )
        response.raise_for_status()

    config = decrypt_config(connection.encrypted_config)
    subscriptions = config.get("subscriptions")
    if not isinstance(subscriptions, dict):
        subscriptions = {}
    subscriptions[channel] = {
        "sender": sender,
        "subscription_id": subscription_id,
        "profile_id": profile_id,
        "auth_id": auth_id,
        "webhook_url": webhook_url,
    }
    config["subscriptions"] = subscriptions
    connection.encrypted_config = encrypt_config(config)
    connection.last_error = None
    await session.flush()
    return True


async def remove_event_subscription(
    session: AsyncSession,
    connection: CommunicationConnection,
    channel: str,
) -> None:
    channel = channel.lower()
    if channel not in INFOBIP_SUBSCRIPTION_EVENTS:
        return
    config = decrypt_config(connection.encrypted_config)
    marker = _subscription_marker(config, channel)
    if marker is None:
        return

    authorization, base_url = await authorization_for_connection(session, connection)
    subscription_id, profile_id, auth_id = _subscription_ids(connection, channel)
    subscription_id = str(marker.get("subscription_id") or subscription_id)
    profile_id = str(marker.get("profile_id") or profile_id)
    auth_id = str(marker.get("auth_id") or auth_id)
    urls = (
        f"{base_url}/subscriptions/1/subscription/{channel.upper()}/{quote(subscription_id, safe='')}",
        f"{base_url}/subscriptions/1/profiles/{quote(profile_id, safe='')}",
        f"{base_url}/subscriptions/1/security/{quote(auth_id, safe='')}",
    )
    for url in urls:
        response = await _subscription_request("DELETE", url, authorization)
        if response.status_code not in {200, 202, 204, 404}:
            response.raise_for_status()

    config = decrypt_config(connection.encrypted_config)
    subscriptions = config.get("subscriptions")
    if isinstance(subscriptions, dict):
        subscriptions.pop(channel, None)
        if subscriptions:
            config["subscriptions"] = subscriptions
        else:
            config.pop("subscriptions", None)
    connection.encrypted_config = encrypt_config(config)
    await session.flush()


async def remove_all_event_subscriptions(
    session: AsyncSession,
    connection: CommunicationConnection,
) -> None:
    config = decrypt_config(connection.encrypted_config)
    subscriptions = config.get("subscriptions")
    if not isinstance(subscriptions, dict):
        return
    for channel in tuple(subscriptions):
        if channel in INFOBIP_SUBSCRIPTION_EVENTS:
            await remove_event_subscription(session, connection, channel)


def verify_webhook_basic_authorization(
    authorization: str | None,
    connection: CommunicationConnection,
) -> bool:
    """Verify CPaaS X Basic authentication when a managed subscription is active.

    Legacy per-message callbacks did not carry Authorization, so connections without
    managed subscriptions remain compatible during migration.
    """
    config = decrypt_config(connection.encrypted_config)
    subscriptions = config.get("subscriptions")
    if not isinstance(subscriptions, dict) or not subscriptions:
        return True
    if not authorization or not authorization.startswith("Basic ") or not connection.webhook_key:
        return False
    try:
        decoded = base64.b64decode(authorization[6:].strip(), validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(username, INFOBIP_WEBHOOK_USERNAME) and hmac.compare_digest(
        password, connection.webhook_key
    )


async def send_infobip_message(
    *,
    authorization: str,
    base_url: str,
    channel: str,
    sender: str,
    recipient: str,
    content: CanonicalMessage,
    callback_data: str,
    webhook_url: str | None = None,
) -> str:
    del webhook_url  # CPaaS X subscriptions own callback routing; per-message URLs override them.
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

    message: dict[str, Any] = {
        "channel": api_channel,
        "sender": sender,
        "destinations": [{"to": recipient}],
        "callbackData": callback_data,
    }
    if channel == "whatsapp":
        if not content.whatsapp_template_values:
            raise ValueError(
                "Internal WhatsApp requires the protected Zahlmeister payment-request template with payment link"
            )
        body: dict[str, Any] = {"type": "TEXT"}
        for index, value in enumerate(content.whatsapp_template_values, start=1):
            body[str(index)] = value
        message["content"] = {"body": body}
        message["template"] = {
            "templateName": INFOBIP_WHATSAPP_TEMPLATE_NAME,
            "language": content.language,
        }
    else:
        message["content"] = {"body": {"text": content.text, "type": "TEXT"}}

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


def oauth_connection_config(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": str(payload.get("token") or ""),
        "token_type": str(payload.get("tokenType") or "IBSSO"),
        "obtained_at": time.time(),
        "base_url": _oauth_base_url(payload),
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
