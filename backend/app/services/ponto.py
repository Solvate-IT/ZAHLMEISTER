from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import ssl
import time
from pathlib import Path
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import BankSyncConnection
from app.services.secrets import decrypt_config, encrypt_config


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sign_state(connection_id: str, organization_id: str, ttl_seconds: int = 600) -> str:
    payload = json.dumps(
        {"connection_id": connection_id, "organization_id": organization_id, "exp": int(time.time()) + ttl_seconds},
        separators=(",", ":"),
    ).encode()
    body = _b64url(payload)
    signature = _b64url(hmac.new(settings.app_secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_state(value: str) -> tuple[str, str]:
    try:
        body, signature = value.split(".", 1)
        expected = _b64url(hmac.new(settings.app_secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid Ponto OAuth state")
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("Expired Ponto OAuth state")
        return str(payload["connection_id"]), str(payload["organization_id"])
    except Exception as exc:
        if isinstance(exc, ValueError) and "Ponto OAuth state" in str(exc):
            raise
        raise ValueError("Invalid Ponto OAuth state") from exc


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    cert = settings.ponto_connect_cert_path.strip()
    key = settings.ponto_connect_key_path.strip()
    if not cert or not key:
        raise ValueError("Ponto Connect client certificate is not configured")
    context.load_cert_chain(certfile=cert, keyfile=key, password=settings.ponto_connect_key_password or None)
    return context


def redirect_uri() -> str:
    return f"{settings.oauth_callback_base}/api/v1/bank-sync/ponto/callback"


def configured() -> bool:
    cert = settings.ponto_connect_cert_path.strip()
    key = settings.ponto_connect_key_path.strip()
    return bool(
        settings.ponto_connect_client_id
        and settings.ponto_connect_client_secret
        and cert
        and key
        and Path(cert).is_file()
        and Path(key).is_file()
    )


def start_authorization(connection: BankSyncConnection, organization_id: str, language: str = "en") -> str:
    if not configured():
        raise ValueError("Ponto Connect is not configured for this Zahlmeister installation")
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    config = decrypt_config(connection.encrypted_config)
    config.update({"pkce_verifier": verifier, "oauth_started_at": time.time()})
    connection.encrypted_config = encrypt_config(config)
    state = sign_state(str(connection.id), organization_id)
    query = urlencode(
        {
            "client_id": settings.ponto_connect_client_id,
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": settings.ponto_connect_scope,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "language": language if language in {"en", "fr", "nl"} else "en",
        }
    )
    return f"{settings.ponto_connect_authorize_url}?{query}"


def _basic_auth() -> str:
    raw = f"{settings.ponto_connect_client_id}:{settings.ponto_connect_client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def _token_request(data: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(verify=_ssl_context(), timeout=30) as client:
        response = await client.post(
            settings.ponto_connect_token_url,
            headers={"Authorization": _basic_auth(), "Accept": "application/vnd.api+json"},
            data=data,
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Invalid Ponto token response")
    return payload


async def exchange_code(connection: BankSyncConnection, code: str) -> dict[str, Any]:
    config = decrypt_config(connection.encrypted_config)
    verifier = str(config.get("pkce_verifier") or "")
    if not verifier:
        raise ValueError("Missing Ponto PKCE verifier")
    payload = await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
            "code_verifier": verifier,
        }
    )
    config.pop("pkce_verifier", None)
    config.pop("oauth_started_at", None)
    config.update(
        {
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token"),
            "expires_at": time.time() + int(payload.get("expires_in") or 0),
        }
    )
    connection.encrypted_config = encrypt_config(config)
    connection.status = "connected"
    connection.connected_at = datetime.now(UTC)
    connection.last_error = None
    return payload


async def access_token(session: AsyncSession, connection: BankSyncConnection) -> str:
    config = decrypt_config(connection.encrypted_config)
    access = str(config.get("access_token") or "")
    expires_at = float(config.get("expires_at") or 0)
    if access and expires_at > time.time() + 60:
        return access
    refresh = str(config.get("refresh_token") or "")
    if not refresh:
        raise ValueError("Ponto refresh token missing")
    payload = await _token_request({"grant_type": "refresh_token", "refresh_token": refresh})
    config.update(
        {
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token") or refresh,
            "expires_at": time.time() + int(payload.get("expires_in") or 0),
        }
    )
    connection.encrypted_config = encrypt_config(config)
    await session.flush()
    return str(payload.get("access_token") or "")


async def api_request(
    session: AsyncSession,
    connection: BankSyncConnection,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    token = await access_token(session, connection)
    url = f"{settings.ponto_connect_api_url.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(verify=_ssl_context(), timeout=30) as client:
        response = await client.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.api+json",
            },
            params=params,
        )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _resource_attributes(resource: dict[str, Any]) -> dict[str, Any]:
    attrs = resource.get("attributes")
    return attrs if isinstance(attrs, dict) else {}


def parse_amount(value: Any) -> tuple[str, str]:
    if isinstance(value, dict):
        return str(value.get("value") or "0"), str(value.get("currency") or "EUR")
    return "0", "EUR"
