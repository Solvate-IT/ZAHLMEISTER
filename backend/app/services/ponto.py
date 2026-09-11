from __future__ import annotations

import base64
import hashlib
import secrets
import ssl
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

from app.core.config import settings
from app.models.entities import BankSyncConnection
from app.services.secrets import decrypt_config, encrypt_config


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def create_oauth_state(
    organization_id: str,
    verifier: str,
    ttl_seconds: int = 600,
) -> str:
    """Create an authenticated, encrypted OAuth state including the PKCE verifier.

    Keeping the short-lived PKCE verifier in the state makes OAuth start fully
    stateless. No provisional BankSyncConnection row or database lock is needed
    before the customer has actually authorized Ponto.
    """
    return encrypt_config(
        {
            "purpose": "ponto_oauth",
            "organization_id": organization_id,
            "pkce_verifier": verifier,
            "ponto_environment": settings.ponto_connect_environment,
            "exp": int(time.time()) + ttl_seconds,
        }
    )


def verify_oauth_state(value: str) -> tuple[str, str]:
    try:
        payload = decrypt_config(value)
        if payload.get("purpose") != "ponto_oauth":
            raise ValueError("Invalid Ponto OAuth state")
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("Expired Ponto OAuth state")
        if payload.get("ponto_environment") != settings.ponto_connect_environment:
            raise ValueError("Ponto OAuth environment changed")
        organization_id = str(payload["organization_id"]).strip()
        verifier = str(payload["pkce_verifier"]).strip()
        if not organization_id or not verifier:
            raise ValueError("Invalid Ponto OAuth state")
        return organization_id, verifier
    except ValueError as exc:
        if str(exc) in {
            "Invalid Ponto OAuth state",
            "Expired Ponto OAuth state",
            "Ponto OAuth environment changed",
        }:
            raise
        raise ValueError("Invalid Ponto OAuth state") from exc
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid Ponto OAuth state") from exc


def _endpoint_configuration_errors() -> list[str]:
    errors: list[str] = []
    api = urlparse(settings.ponto_connect_api_url.strip())
    token = urlparse(settings.ponto_connect_token_url.strip())
    authorization = urlparse(settings.ponto_authorization_url)
    expected_authorization_host = (
        "sandbox-authorization.myponto.com"
        if settings.ponto_connect_environment == "sandbox"
        else "authorization.myponto.com"
    )
    if api.scheme != "https" or api.hostname != "api.ibanity.com" or not api.path.startswith("/ponto-connect"):
        errors.append("api_url")
    if token.scheme != "https" or token.hostname != "api.ibanity.com" or not token.path.startswith("/ponto-connect/"):
        errors.append("token_url")
    if authorization.scheme != "https" or authorization.hostname != expected_authorization_host:
        errors.append("authorization_url_environment")
    return errors


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
    missing.extend(_endpoint_configuration_errors())
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


def start_authorization(organization_id: str, language: str = "en") -> str:
    status = configuration_status()
    if not status["configured"]:
        raise ValueError(
            "Ponto Connect configuration is incomplete: " + ", ".join(status["missing"])
        )
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = create_oauth_state(organization_id, verifier)
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


def _revoke_url() -> str:
    token = urlparse(settings.ponto_connect_token_url.strip())
    path = token.path.rsplit("/", 1)[0] + "/revoke"
    return urlunparse((token.scheme, token.netloc, path, "", "", ""))


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


async def revoke_connection(connection: BankSyncConnection) -> None:
    """Revoke the remote Ponto refresh token before local credentials are removed."""
    config = decrypt_config(connection.encrypted_config)
    stored_environment = str(config.get("ponto_environment") or "")
    if stored_environment and stored_environment != settings.ponto_connect_environment:
        raise ValueError("Ponto connection belongs to a different environment; reconnect it")
    refresh_token = str(config.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ValueError(
            "Ponto refresh token is missing; revoke the integration in Ponto before disconnecting it locally"
        )
    async with httpx.AsyncClient(verify=_ssl_context(), timeout=30) as client:
        response = await client.post(
            _revoke_url(),
            data={"token": refresh_token},
            headers={
                "Authorization": _basic_auth(),
                "Accept": "application/vnd.api+json, application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    if response.status_code not in {200, 204}:
        response.raise_for_status()


async def exchange_code(code: str, verifier: str) -> dict[str, Any]:
    if not verifier:
        raise ValueError("Ponto PKCE verifier missing")
    payload = await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.ponto_connect_client_id,
            "redirect_uri": redirect_uri(),
            "code_verifier": verifier,
        }
    )
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in") or 1800) - 60,
        "scope": payload.get("scope"),
        "ponto_environment": settings.ponto_connect_environment,
    }


def apply_authorization(connection: BankSyncConnection, config: dict[str, Any]) -> None:
    connection.encrypted_config = encrypt_config(config)
    connection.status = "connected"
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
        if path_or_url.startswith(("http://", "https://"))
        else f"{base}/{path_or_url.lstrip('/')}"
    )
    parsed = urlparse(url)
    base_parsed = urlparse(base)
    if parsed.hostname != base_parsed.hostname or not parsed.path.startswith(base_parsed.path.rstrip("/") + "/"):
        raise ValueError("Ponto API returned an unexpected pagination URL")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Ponto API returned an unexpected pagination URL")
    # The API is HTTPS-only, while some Ponto v2 pagination examples still expose
    # http:// links. Upgrade same-host links rather than following plaintext HTTP.
    return urlunparse(("https", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


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
