from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.billing_catalog import PRO_YEARLY_TARIFF
from app.core.config import settings
from app.models.platform import StoreSubscription
from app.services.billing import VerifiedSubscription, apply_verified_subscription
from app.services.secrets import decrypt_config

logger = logging.getLogger(__name__)

GOOGLE_PLAY_PACKAGE_NAME = "at.solvate.zahlmeister"
GOOGLE_PLAY_BASE_PLAN_ID = "yearly"
GOOGLE_PLAY_PRODUCT_ID = PRO_YEARLY_TARIFF.product_id
GOOGLE_PLAY_API_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
GOOGLE_OIDC_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_PLAY_CREDENTIALS_FILE = Path("/run/secrets/internal/google_play_service_account.json")

_STATE_MAP = {
    "SUBSCRIPTION_STATE_PENDING": "pending",
    "SUBSCRIPTION_STATE_ACTIVE": "active",
    "SUBSCRIPTION_STATE_PAUSED": "on_hold",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace_period",
    "SUBSCRIPTION_STATE_ON_HOLD": "on_hold",
    "SUBSCRIPTION_STATE_CANCELED": "cancelled",
    "SUBSCRIPTION_STATE_EXPIRED": "expired",
    "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED": "expired",
}


class GooglePlayBillingUnavailable(RuntimeError):
    pass


class GooglePlayBillingVerificationError(RuntimeError):
    pass


def google_play_credentials_available() -> bool:
    return GOOGLE_PLAY_CREDENTIALS_FILE.is_file()


def google_play_rtdn_audience() -> str:
    return f"{settings.oauth_callback_base.rstrip('/')}/api/v1/billing/google/rtdn"


def google_play_config() -> dict[str, object]:
    return {
        "available": google_play_credentials_available(),
        "package_name": GOOGLE_PLAY_PACKAGE_NAME,
        "product_id": GOOGLE_PLAY_PRODUCT_ID,
        "base_plan_id": GOOGLE_PLAY_BASE_PLAN_ID,
    }


def _load_service_account() -> dict[str, str]:
    if not GOOGLE_PLAY_CREDENTIALS_FILE.is_file():
        raise GooglePlayBillingUnavailable(
            "Google Play service account credentials are not configured"
        )
    try:
        payload = json.loads(GOOGLE_PLAY_CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GooglePlayBillingUnavailable("Google Play credentials are invalid") from exc
    if not isinstance(payload, dict) or payload.get("type") != "service_account":
        raise GooglePlayBillingUnavailable("Google Play credentials are invalid")
    client_email = str(payload.get("client_email") or "").strip()
    private_key = str(payload.get("private_key") or "").strip()
    if not client_email or not private_key:
        raise GooglePlayBillingUnavailable("Google Play credentials are incomplete")
    return {"client_email": client_email, "private_key": private_key}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding_len = (-len(value)) % 4
    return base64.urlsafe_b64decode(value + ("=" * padding_len))


def _service_account_assertion(credentials: dict[str, str], now: int) -> str:
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": credentials["client_email"],
        "scope": GOOGLE_OAUTH_SCOPE,
        "aud": GOOGLE_OAUTH_TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    encoded_header = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_claims = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    try:
        key = serialization.load_pem_private_key(
            credentials["private_key"].encode("utf-8"), password=None
        )
        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    except (TypeError, ValueError) as exc:
        raise GooglePlayBillingUnavailable("Google Play private key is invalid") from exc
    return f"{encoded_header}.{encoded_claims}.{_b64url(signature)}"


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GooglePlayBillingVerificationError("Google Play returned an invalid timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _purchase_reference(purchase_token: str) -> str:
    digest = hashlib.sha256(purchase_token.encode("utf-8")).hexdigest()
    return f"google:{digest}"


def _purchase_status(payload: dict[str, Any]) -> str:
    state = str(payload.get("subscriptionState") or "")
    status = _STATE_MAP.get(state)
    if status is None:
        raise GooglePlayBillingVerificationError("Unsupported Google Play subscription state")
    return status


def _line_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("lineItems")
    if not isinstance(raw, list):
        raise GooglePlayBillingVerificationError("Google Play subscription has no line items")
    rows = [item for item in raw if isinstance(item, dict)]
    if not rows:
        raise GooglePlayBillingVerificationError("Google Play subscription has no line items")
    if not any(str(item.get("productId") or "") == GOOGLE_PLAY_PRODUCT_ID for item in rows):
        raise GooglePlayBillingVerificationError("Unexpected Google Play subscription product")
    return rows


def _expiry(rows: list[dict[str, Any]]) -> datetime | None:
    values = [_parse_time(item.get("expiryTime")) for item in rows]
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _auto_renew(rows: list[dict[str, Any]]) -> bool | None:
    values: list[bool] = []
    for item in rows:
        plan = item.get("autoRenewingPlan")
        if isinstance(plan, dict) and isinstance(plan.get("autoRenewEnabled"), bool):
            values.append(bool(plan["autoRenewEnabled"]))
    if not values:
        return None
    return any(values)


def _account_identifier(payload: dict[str, Any]) -> str | None:
    identifiers = payload.get("externalAccountIdentifiers")
    if not isinstance(identifiers, dict):
        return None
    value = identifiers.get("obfuscatedExternalAccountId")
    return str(value).strip() if value else None


class GooglePlayClient:
    def __init__(self) -> None:
        self._access_token = ""
        self._access_token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._jwks: dict[str, rsa.RSAPublicKey] = {}
        self._jwks_expires_at = 0.0
        self._jwks_lock = asyncio.Lock()

    async def access_token(self) -> str:
        if self._access_token and self._access_token_expires_at > time.time() + 60:
            return self._access_token
        async with self._token_lock:
            if self._access_token and self._access_token_expires_at > time.time() + 60:
                return self._access_token
            credentials = _load_service_account()
            now = int(time.time())
            assertion = _service_account_assertion(credentials, now)
            async with httpx.AsyncClient(timeout=15.0) as client:
                try:
                    response = await client.post(
                        GOOGLE_OAUTH_TOKEN_URL,
                        data={
                            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                            "assertion": assertion,
                        },
                    )
                except httpx.HTTPError as exc:
                    raise GooglePlayBillingUnavailable(
                        "Google Play authentication is unavailable"
                    ) from exc
            if response.status_code != 200:
                logger.warning("Google Play OAuth failed with HTTP %s", response.status_code)
                raise GooglePlayBillingUnavailable("Google Play authentication failed")
            try:
                payload = response.json()
                token = str(payload["access_token"])
                expires_in = max(300, int(payload.get("expires_in", 3600)))
            except (ValueError, KeyError, TypeError) as exc:
                raise GooglePlayBillingUnavailable("Google Play authentication failed") from exc
            self._access_token = token
            self._access_token_expires_at = time.time() + expires_in
            return token

    async def subscription(self, purchase_token: str) -> dict[str, Any]:
        token = await self.access_token()
        url = (
            f"{GOOGLE_PLAY_API_BASE}/applications/{quote(GOOGLE_PLAY_PACKAGE_NAME, safe='')}"
            f"/purchases/subscriptionsv2/tokens/{quote(purchase_token, safe='')}"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as exc:
                raise GooglePlayBillingUnavailable("Google Play verification is unavailable") from exc
        if response.status_code == 404:
            raise GooglePlayBillingVerificationError("Google Play purchase was not found")
        if response.status_code in {401, 403}:
            raise GooglePlayBillingUnavailable("Google Play API access is not authorized")
        if response.status_code != 200:
            logger.warning("Google Play subscription lookup failed with HTTP %s", response.status_code)
            raise GooglePlayBillingVerificationError("Google Play purchase could not be verified")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GooglePlayBillingVerificationError("Google Play returned invalid data") from exc
        if not isinstance(payload, dict):
            raise GooglePlayBillingVerificationError("Google Play returned invalid data")
        return payload

    async def acknowledge(self, purchase_token: str) -> None:
        token = await self.access_token()
        url = (
            f"{GOOGLE_PLAY_API_BASE}/applications/{quote(GOOGLE_PLAY_PACKAGE_NAME, safe='')}"
            f"/purchases/subscriptions/{quote(GOOGLE_PLAY_PRODUCT_ID, safe='')}"
            f"/tokens/{quote(purchase_token, safe='')}:acknowledge"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json={},
                )
            except httpx.HTTPError as exc:
                raise GooglePlayBillingUnavailable(
                    "Google Play purchase acknowledgement is unavailable"
                ) from exc
        if response.status_code not in {200, 204, 409}:
            logger.warning("Google Play acknowledgement failed with HTTP %s", response.status_code)
            raise GooglePlayBillingVerificationError(
                "Google Play purchase could not be acknowledged"
            )

    async def _refresh_jwks(self) -> dict[str, rsa.RSAPublicKey]:
        if self._jwks and self._jwks_expires_at > time.time() + 60:
            return self._jwks
        async with self._jwks_lock:
            if self._jwks and self._jwks_expires_at > time.time() + 60:
                return self._jwks
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    response = await client.get(GOOGLE_OIDC_JWKS_URL)
                except httpx.HTTPError as exc:
                    raise GooglePlayBillingUnavailable(
                        "Google identity verification is unavailable"
                    ) from exc
            if response.status_code != 200:
                raise GooglePlayBillingUnavailable("Google identity verification failed")
            try:
                raw = response.json().get("keys", [])
            except (ValueError, AttributeError) as exc:
                raise GooglePlayBillingUnavailable("Google identity verification failed") from exc
            keys: dict[str, rsa.RSAPublicKey] = {}
            for item in raw:
                if not isinstance(item, dict) or item.get("kty") != "RSA" or item.get("alg") != "RS256":
                    continue
                try:
                    kid = str(item["kid"])
                    n = int.from_bytes(_b64url_decode(str(item["n"])), "big")
                    e = int.from_bytes(_b64url_decode(str(item["e"])), "big")
                    keys[kid] = rsa.RSAPublicNumbers(e, n).public_key()
                except (KeyError, ValueError):
                    continue
            if not keys:
                raise GooglePlayBillingUnavailable("Google identity verification failed")
            self._jwks = keys
            self._jwks_expires_at = time.time() + 3600
            return keys

    async def verify_pubsub_oidc(self, authorization: str | None) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise GooglePlayBillingVerificationError("Missing Pub/Sub authentication")
        token = authorization[7:].strip()
        parts = token.split(".")
        if len(parts) != 3:
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub authentication")
        try:
            header = json.loads(_b64url_decode(parts[0]))
            claims = json.loads(_b64url_decode(parts[1]))
        except (ValueError, json.JSONDecodeError) as exc:
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub authentication") from exc
        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub authentication")
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub authentication")
        keys = await self._refresh_jwks()
        key = keys.get(str(header["kid"]))
        if key is None:
            self._jwks_expires_at = 0
            keys = await self._refresh_jwks()
            key = keys.get(str(header["kid"]))
        if key is None:
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub authentication")
        try:
            key.verify(
                _b64url_decode(parts[2]),
                f"{parts[0]}.{parts[1]}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError) as exc:
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub authentication") from exc

        now = int(time.time())
        issuer = str(claims.get("iss") or "")
        audience = claims.get("aud")
        audiences = {str(item) for item in audience} if isinstance(audience, list) else {str(audience)}
        email = str(claims.get("email") or "")
        try:
            expires_at = int(claims.get("exp", 0))
            issued_at = int(claims.get("iat", 0))
        except (TypeError, ValueError) as exc:
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub authentication") from exc
        credentials = _load_service_account()
        if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub authentication")
        if google_play_rtdn_audience() not in audiences:
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub audience")
        if email != credentials["client_email"] or claims.get("email_verified") is not True:
            raise GooglePlayBillingVerificationError("Invalid Pub/Sub service account")
        if expires_at < now - 60 or issued_at > now + 60:
            raise GooglePlayBillingVerificationError("Expired Pub/Sub authentication")


google_play_client = GooglePlayClient()


def verified_subscription_from_google(
    organization_id: UUID,
    purchase_token: str,
    payload: dict[str, Any],
    *,
    require_account_match: bool,
) -> VerifiedSubscription:
    rows = _line_items(payload)
    account_identifier = _account_identifier(payload)
    if require_account_match and account_identifier != str(organization_id):
        raise GooglePlayBillingVerificationError(
            "Google Play purchase belongs to another Zahlmeister account"
        )
    return VerifiedSubscription(
        provider="google",
        product_id=GOOGLE_PLAY_PRODUCT_ID,
        external_reference=_purchase_reference(purchase_token),
        account_token=str(organization_id),
        status=_purchase_status(payload),
        purchased_at=_parse_time(payload.get("startTime")),
        expires_at=_expiry(rows),
        auto_renew=_auto_renew(rows),
        environment="test" if isinstance(payload.get("testPurchase"), dict) else "production",
        verification_data={"purchase_token": purchase_token},
    )


async def verify_google_purchase(
    session: AsyncSession,
    organization_id: UUID,
    purchase_token: str,
) -> StoreSubscription:
    purchase_token = purchase_token.strip()
    if not purchase_token or len(purchase_token) > 4096:
        raise GooglePlayBillingVerificationError("Invalid Google Play purchase token")

    payload: dict[str, Any] | None = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            payload = await google_play_client.subscription(purchase_token)
            break
        except GooglePlayBillingVerificationError as exc:
            last_error = exc
            if "not found" not in str(exc).lower() or attempt == 2:
                raise
            await asyncio.sleep(attempt + 1)
    if payload is None:
        raise GooglePlayBillingVerificationError("Google Play purchase could not be verified") from last_error

    verified = verified_subscription_from_google(
        organization_id,
        purchase_token,
        payload,
        require_account_match=True,
    )
    subscription = await apply_verified_subscription(session, organization_id, verified)
    if (
        payload.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_PENDING"
        and verified.status in {"active", "grace_period", "cancelled"}
    ):
        await google_play_client.acknowledge(purchase_token)
    return subscription


async def sync_google_subscription(
    session: AsyncSession,
    organization_id: UUID,
    *,
    purchase_token: str | None = None,
) -> StoreSubscription | None:
    subscription = await session.scalar(
        select(StoreSubscription)
        .where(
            StoreSubscription.organization_id == organization_id,
            StoreSubscription.provider == "google",
        )
        .with_for_update()
    )
    if subscription is None and not purchase_token:
        return None

    token = purchase_token
    if not token and subscription is not None:
        token = str(
            decrypt_config(subscription.verification_data_encrypted).get("purchase_token") or ""
        )
    token = (token or "").strip()
    if not token:
        raise GooglePlayBillingVerificationError("Stored Google Play purchase token is missing")

    payload = await google_play_client.subscription(token)
    verified = verified_subscription_from_google(
        organization_id,
        token,
        payload,
        require_account_match=False,
    )
    return await apply_verified_subscription(session, organization_id, verified)


async def organization_for_purchase_token(
    session: AsyncSession,
    purchase_token: str,
) -> UUID | None:
    reference = _purchase_reference(purchase_token)
    return await session.scalar(
        select(StoreSubscription.organization_id).where(
            StoreSubscription.provider == "google",
            StoreSubscription.external_reference == reference,
        )
    )


def decode_rtdn_payload(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    message = payload.get("message")
    if not isinstance(message, dict):
        raise GooglePlayBillingVerificationError("Invalid Pub/Sub message")
    raw_data = message.get("data")
    if not isinstance(raw_data, str) or not raw_data:
        raise GooglePlayBillingVerificationError("Invalid Pub/Sub message")
    try:
        decoded = base64.b64decode(raw_data, validate=True)
        notification = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GooglePlayBillingVerificationError("Invalid Pub/Sub message") from exc
    if not isinstance(notification, dict):
        raise GooglePlayBillingVerificationError("Invalid Pub/Sub message")
    if notification.get("packageName") != GOOGLE_PLAY_PACKAGE_NAME:
        raise GooglePlayBillingVerificationError("Unexpected Google Play package")
    subscription = notification.get("subscriptionNotification")
    if not isinstance(subscription, dict):
        return str(message.get("messageId") or "") or None, None
    purchase_token = str(subscription.get("purchaseToken") or "").strip()
    if not purchase_token:
        raise GooglePlayBillingVerificationError("Google Play notification token is missing")
    return str(message.get("messageId") or "") or None, purchase_token


async def process_google_rtdn(
    session: AsyncSession,
    payload: dict[str, Any],
    authorization: str | None,
) -> UUID | None:
    await google_play_client.verify_pubsub_oidc(authorization)
    _message_id, purchase_token = decode_rtdn_payload(payload)
    if purchase_token is None:
        return None

    provider_payload = await google_play_client.subscription(purchase_token)
    organization_id = await organization_for_purchase_token(session, purchase_token)
    if organization_id is None:
        account_identifier = _account_identifier(provider_payload)
        try:
            organization_id = UUID(account_identifier) if account_identifier else None
        except ValueError:
            organization_id = None
    if organization_id is None:
        logger.info("Ignored Google Play notification for an unlinked purchase")
        return None

    verified = verified_subscription_from_google(
        organization_id,
        purchase_token,
        provider_payload,
        require_account_match=True,
    )
    await apply_verified_subscription(session, organization_id, verified)
    return organization_id
