from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
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
        {
            "connection_id": connection_id,
            "organization_id": organization_id,
            "exp": int(time.time()) + ttl_seconds,
        },
        separators=(",", ":"),
    ).encode()
    body = _b64url(payload)
    signature = _b64url(
        hmac.new(settings.app_secret.encode(), body.encode(), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def verify_state(value: str) -> tuple[str, str]:
    try:
        body, signature = value.split(".", 1)
        expected = _b64url(
            hmac.new(settings.app_secret.encode(), body.encode(), hashlib.sha256).digest()
        )
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


def configuration_status() -> dict[str, Any]:
    cert = settings.ponto_connect_cert_path.strip()
    key = settings.ponto_connect_key_path.strip()
    missing: list[str] = []
    if not settings.ponto_connect_client_id.strip():
        missing.append("client_id")
    if not settings.ponto_connect_client_secret.strip():
        missing.append("client_secret")
    if not cert:
        missing.append("client_certificate")
    elif not Path(cert).is_file():
        missing.append("client_certificate_file")
    if not key:
        missing.append("private_key")
    elif not Path(key).is_file():
        missing.append("private_key_file")
    return {
        "environment": settings.ponto_connect_environment,
        "configured": not missing,
        "redirect_uri": redirect_uri(),
        "missing": missing,
    }


def _ssl_context() -> ssl.SSLContext:
    status = configuration_status()
    if status["missing"]:
        raise ValueError(
            "Ponto Connect configuration is incomplete: " + ", ".join(status["missing"])
        )
    context = ssl.create_default_context()
    try:
        context.load_cert_chain(
            certfile=settings.ponto_connect_cert_path.strip(),
            keyfile=settings.ponto_connect_key_path.strip(),
            password=settings.ponto_connect_key_password or None,
        )
    except (OSError, ssl.SSLError) as exc:
        raise ValueError("Ponto Connect client certificate or private key is invalid") from exc
    return context


def redirect_uri() -> str:
    return f"{settings.oauth_callback_base}/api/v1/bank-sync/ponto/callback"


def configured() -> bool:
    return bool(configuration_status()["configured"])


def start_authorization(
    connection: BankSyncConnection, organization_id: str, language: str = "en"
) -> str:
    status = configuration_status()
    if not status["configured"]:
        raise ValueError(
            "Ponto Connect configuration is incomplete: " + ", ".join(status["missing"])
        )
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    config = decrypt_config(connection.encrypted_config)
    config.update(
        {
            "pkce_verifier": verifier,
            "oauth_started_at": time.time(),
            "ponto_environment": settings.ponto_connect_environment,
        }
    )
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
    return f"{settings.ponto_authorization_url}?{query}"


def _basic_auth() -> str:
    raw = f"{settings.ponto_connect_client_id}:{settings.ponto_connect_client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def _token_request(data: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(verify=_ssl_context(), timeout=30) as client:
        response = await client.post(
            settings.ponto_connect_token_url,
            data=data,
            headers={
                "Authorization": _basic_auth(),
                "Accept": "application/vnd.api+json, application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    response.raise_for_status()
    payload = response.json()
    if "access_token" not in payload:
        raise ValueError("Ponto token response did not contain an access token")
    return payload


async def exchange_code(connection: BankSyncConnection, code: str) -> None:
    config = decrypt_config(connection.encrypted_config)
    verifier = str(config.get("pkce_verifier") or "")
    if not verifier:
        raise ValueError("Ponto PKCE verifier missing")
    started_environment = str(config.get("ponto_environment") or "")
    if started_environment and started_environment != settings.ponto_connect_environment:
        raise ValueError("Ponto environment changed while OAuth authorization was in progress")
    payload = await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.ponto_connect_client_id,
            "redirect_uri": redirect_uri(),
            "code_verifier": verifier,
        }
    )
    config.update(
        {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token"),
            "expires_at": time.time() + int(payload.get("expires_in") or 1800) - 60,
            "scope": payload.get("scope"),
        }
    )
    config.pop("pkce_verifier", None)
    config.pop("oauth_started_at", None)
    connection.encrypted_config = encrypt_config(config)
    connection.status = "connected"
    connection.connected_at = datetime.now(UTC)
    connection.last_error = None


async def access_token(connection: BankSyncConnection) -> str:
    config = decrypt_config(connection.encrypted_config)
    stored_environment = str(config.get("ponto_environment") or "")
    if stored_environment and stored_environment != settings.ponto_connect_environment:
        raise ValueError("Ponto connection belongs to a different environment; reconnect it")
    token = str(config.get("access_token") or "")
    if token and float(config.get("expires_at") or 0) > time.time():
        return token

    from app.db.session import SessionLocal

    async with SessionLocal.begin() as session:
        stored = await session.get(BankSyncConnection, connection.id, with_for_update=True)
        if stored is None:
            raise ValueError("Ponto connection no longer exists")
        fresh_config = decrypt_config(stored.encrypted_config)
        stored_environment = str(fresh_config.get("ponto_environment") or "")
        if stored_environment and stored_environment != settings.ponto_connect_environment:
            raise ValueError("Ponto connection belongs to a different environment; reconnect it")
        fresh_token = str(fresh_config.get("access_token") or "")
        if fresh_token and float(fresh_config.get("expires_at") or 0) > time.time():
            return fresh_token
        refresh = str(fresh_config.get("refresh_token") or "")
        if not refresh:
            raise ValueError("Ponto refresh token missing; reconnect the bank account")
        payload = await _token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": settings.ponto_connect_client_id,
            }
        )
        fresh_config.update(
            {
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token") or refresh,
                "expires_at": time.time() + int(payload.get("expires_in") or 1800) - 60,
                "scope": payload.get("scope") or fresh_config.get("scope"),
            }
        )
        stored.encrypted_config = encrypt_config(fresh_config)
        stored.last_error = None
        return str(payload["access_token"])


def _safe_api_url(path_or_url: str) -> str:
    base = settings.ponto_connect_api_url.rstrip("/")
    url = (
        path_or_url
        if path_or_url.startswith("https://")
        else f"{base}/{path_or_url.lstrip('/')}"
    )
    parsed = urlparse(url)
    base_parsed = urlparse(base)
    if parsed.scheme != "https" or parsed.hostname != base_parsed.hostname:
        raise ValueError("Ponto API returned an unexpected pagination URL")
    return url


async def _get(connection: BankSyncConnection, path_or_url: str) -> dict[str, Any]:
    token = await access_token(connection)
    url = _safe_api_url(path_or_url)
    async with httpx.AsyncClient(verify=_ssl_context(), timeout=30) as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.api+json, application/json",
            },
        )
    if response.status_code in {401, 403}:
        raise ValueError("Ponto authorization is no longer valid; reconnect the bank account")
    response.raise_for_status()
    return response.json()


async def list_accounts(connection: BankSyncConnection) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    next_url: str | None = (
        f"{settings.ponto_connect_api_url.rstrip('/')}/accounts?page[limit]=100"
    )
    while next_url:
        payload = await _get(connection, next_url)
        for item in payload.get("data") or []:
            if isinstance(item, dict):
                result.append(item)
        links = payload.get("links") or {}
        next_url = links.get("next") if isinstance(links, dict) else None
    return result


async def list_transactions(
    connection: BankSyncConnection, account_external_id: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    next_url: str | None = (
        f"{settings.ponto_connect_api_url.rstrip('/')}/accounts/"
        f"{account_external_id}/transactions?page[limit]=100"
    )
    while next_url:
        payload = await _get(connection, next_url)
        for item in payload.get("data") or []:
            if isinstance(item, dict):
                result.append(item)
        links = payload.get("links") or {}
        next_url = links.get("next") if isinstance(links, dict) else None
    return result


async def test_connection(connection: BankSyncConnection) -> None:
    await list_accounts(connection)
