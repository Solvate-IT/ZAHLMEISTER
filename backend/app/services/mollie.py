from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import OnlinePaymentConnection
from app.services.online_payment_providers import OnlineCheckout, OnlinePaymentStatus
from app.services.secrets import decrypt_config, encrypt_config

PROVIDER = "mollie"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


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
        if isinstance(exc, ValueError) and str(exc) in {"Invalid OAuth state", "Expired OAuth state"}:
            raise
        raise ValueError("Invalid OAuth state") from exc


def oauth_redirect_uri() -> str:
    return f"{settings.public_app_url.rstrip('/')}/api/v1/online-payments/mollie/oauth/callback"


def oauth_authorization_url(organization_id: str) -> str:
    if not settings.mollie_oauth_client_id or not settings.mollie_oauth_client_secret:
        raise ValueError("Mollie Connect is not configured for this Zahlmeister installation")
    query = urlencode(
        {
            "client_id": settings.mollie_oauth_client_id,
            "redirect_uri": oauth_redirect_uri(),
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": settings.mollie_oauth_scopes,
            "state": sign_oauth_state(organization_id),
        }
    )
    return f"{settings.mollie_oauth_authorize_url}?{query}"


async def exchange_oauth_code(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.mollie_oauth_token_url,
            auth=(settings.mollie_oauth_client_id, settings.mollie_oauth_client_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": oauth_redirect_uri(),
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    if not payload.get("access_token") or not payload.get("refresh_token"):
        raise ValueError("Mollie OAuth response did not contain the required tokens")
    return payload


async def _refresh_oauth_token(config: dict[str, Any]) -> dict[str, Any]:
    refresh_token = str(config.get("refresh_token") or "")
    if not refresh_token:
        raise ValueError("Mollie refresh token missing")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.mollie_oauth_token_url,
            auth=(settings.mollie_oauth_client_id, settings.mollie_oauth_client_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": oauth_redirect_uri(),
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    if not payload.get("access_token"):
        raise ValueError("Mollie OAuth refresh did not contain an access token")
    return payload


def oauth_connection_config(payload: dict[str, Any]) -> dict[str, Any]:
    expires_in = int(payload.get("expires_in") or 3600)
    return {
        "access_token": str(payload.get("access_token") or ""),
        "refresh_token": str(payload.get("refresh_token") or ""),
        "expires_at": time.time() + expires_in,
        "scope": str(payload.get("scope") or ""),
        "test_mode": bool(settings.mollie_test_mode),
    }


async def authorization_for_connection(
    session: AsyncSession, connection: OnlinePaymentConnection
) -> str:
    if connection.provider != PROVIDER:
        raise ValueError(f"Unsupported online payment provider: {connection.provider}")
    config = decrypt_config(connection.encrypted_config)
    access_token = str(config.get("access_token") or "")
    expires_at = float(config.get("expires_at") or 0)
    if not access_token or expires_at <= time.time() + 180:
        payload = await _refresh_oauth_token(config)
        config["access_token"] = str(payload["access_token"])
        if payload.get("refresh_token"):
            config["refresh_token"] = str(payload["refresh_token"])
        config["expires_at"] = time.time() + int(payload.get("expires_in") or 3600)
        if payload.get("scope"):
            config["scope"] = str(payload["scope"])
        connection.encrypted_config = encrypt_config(config)
        connection.last_error = None
        await session.flush()
        access_token = str(config["access_token"])
    return f"Bearer {access_token}"


def _testmode(connection: OnlinePaymentConnection) -> bool:
    config = decrypt_config(connection.encrypted_config)
    return bool(config.get("test_mode", False))


async def _request_json(
    method: str,
    path: str,
    *,
    authorization: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": authorization, "Accept": "application/hal+json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method,
            f"{settings.mollie_api_url.rstrip('/')}/{path.lstrip('/')}",
            headers=headers,
            json=json_body,
            params=params,
        )
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected Mollie response")
    return data


async def get_account_details(
    session: AsyncSession, connection: OnlinePaymentConnection
) -> tuple[str | None, list[dict[str, str | None]]]:
    authorization = await authorization_for_connection(session, connection)
    organization = await _request_json(
        "GET", "organizations/me", authorization=authorization
    )
    profiles_payload = await _request_json(
        "GET", "profiles", authorization=authorization
    )
    embedded = profiles_payload.get("_embedded") or {}
    raw_profiles = embedded.get("profiles") or []
    profiles: list[dict[str, str | None]] = []
    for item in raw_profiles:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        profiles.append(
            {
                "id": str(item["id"]),
                "name": str(item.get("name") or item.get("website") or item["id"]),
                "website": str(item.get("website") or "") or None,
                "status": str(item.get("status") or "") or None,
            }
        )
    account_label = str(organization.get("name") or "") or None
    return account_label, profiles


def normalize_locale(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.replace("-", "_")
    language = cleaned.split("_", 1)[0].lower()
    country = cleaned.split("_", 1)[1].upper() if "_" in cleaned else ""
    # Mollie's hosted checkout supports a finite set. Use the closest common locale
    # and let Mollie/browser fall back when a locale is not explicitly supported.
    supported = {
        "ca_ES", "cs_CZ", "da_DK", "de_AT", "de_CH", "de_DE", "de_LU",
        "en_BE", "en_GB", "en_NL", "en_US", "es_ES", "fi_FI", "fr_BE",
        "fr_FR", "fr_LU", "hu_HU", "is_IS", "it_IT", "lt_LT", "lv_LV",
        "nb_NO", "nl_BE", "nl_NL", "pl_PL", "pt_PT", "sk_SK", "sv_SE",
    }
    candidate = f"{language}_{country}" if country else ""
    if candidate in supported:
        return candidate
    preferred = {
        "de": "de_DE", "en": "en_GB", "fr": "fr_FR", "it": "it_IT",
        "es": "es_ES", "pt": "pt_PT", "nl": "nl_NL", "pl": "pl_PL",
        "cs": "cs_CZ", "da": "da_DK", "fi": "fi_FI", "hu": "hu_HU",
        "lt": "lt_LT", "lv": "lv_LV", "sk": "sk_SK", "sv": "sv_SE",
    }
    return preferred.get(language)


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def payment_status_from_payload(payload: dict[str, Any]) -> OnlinePaymentStatus:
    amount = payload.get("amount") or {}
    return OnlinePaymentStatus(
        external_id=str(payload.get("id") or ""),
        status=str(payload.get("status") or "unknown"),
        amount=Decimal(str(amount.get("value") or "0")),
        currency=str(amount.get("currency") or "").upper(),
        method=str(payload.get("method") or "") or None,
        paid_at=parse_datetime(payload.get("paidAt")),
        expires_at=parse_datetime(payload.get("expiresAt")),
    )


class MollieProvider:
    name = PROVIDER

    async def test_connection(
        self, session: AsyncSession, connection: OnlinePaymentConnection
    ) -> None:
        account_label, profiles = await get_account_details(session, connection)
        if not profiles:
            raise ValueError("Mollie account has no payment profile")
        if connection.profile_id and not any(p["id"] == connection.profile_id for p in profiles):
            raise ValueError("Selected Mollie payment profile is no longer available")
        if not connection.profile_id:
            connection.profile_id = str(profiles[0]["id"])
        connection.account_label = account_label or connection.account_label or "Mollie"

    async def create_checkout(
        self,
        session: AsyncSession,
        connection: OnlinePaymentConnection,
        *,
        amount: Decimal,
        currency: str,
        description: str,
        redirect_url: str,
        webhook_url: str,
        metadata: dict[str, str],
        locale: str | None,
        idempotency_key: str,
    ) -> OnlineCheckout:
        if not connection.profile_id:
            raise ValueError("Mollie payment profile is not selected")
        authorization = await authorization_for_connection(session, connection)
        body: dict[str, Any] = {
            "amount": {"currency": currency.upper(), "value": f"{amount:.2f}"},
            "description": description[:255],
            "redirectUrl": redirect_url,
            "webhookUrl": webhook_url,
            "profileId": connection.profile_id,
            "metadata": metadata,
        }
        normalized_locale = normalize_locale(locale)
        if normalized_locale:
            body["locale"] = normalized_locale
        if _testmode(connection):
            body["testmode"] = True
        payload = await _request_json(
            "POST",
            "payments",
            authorization=authorization,
            json_body=body,
            idempotency_key=idempotency_key,
        )
        checkout_url = str(((payload.get("_links") or {}).get("checkout") or {}).get("href") or "")
        external_id = str(payload.get("id") or "")
        if not checkout_url or not external_id:
            raise ValueError("Mollie did not return a checkout URL")
        return OnlineCheckout(
            external_id=external_id,
            checkout_url=checkout_url,
            status=str(payload.get("status") or "open"),
            expires_at=parse_datetime(payload.get("expiresAt")),
        )

    async def get_payment(
        self,
        session: AsyncSession,
        connection: OnlinePaymentConnection,
        external_id: str,
    ) -> OnlinePaymentStatus:
        authorization = await authorization_for_connection(session, connection)
        params = {"testmode": "true"} if _testmode(connection) else None
        payload = await _request_json(
            "GET", f"payments/{external_id}", authorization=authorization, params=params
        )
        return payment_status_from_payload(payload)


mollie_provider = MollieProvider()


async def revoke_connection(connection: OnlinePaymentConnection) -> None:
    config = decrypt_config(connection.encrypted_config)
    refresh_token = str(config.get("refresh_token") or "")
    if not refresh_token or not settings.mollie_oauth_client_id or not settings.mollie_oauth_client_secret:
        return
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                "DELETE",
                settings.mollie_oauth_token_url,
                auth=(settings.mollie_oauth_client_id, settings.mollie_oauth_client_secret),
                data={"token_type_hint": "refresh_token", "token": refresh_token},
                headers={"Accept": "application/json"},
            )
        if response.status_code not in {200, 204, 401, 404}:
            response.raise_for_status()
    except httpx.HTTPError:
        # Local disconnect must remain possible even if Mollie is temporarily unavailable.
        return
