from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.mollie import normalize_locale, oauth_authorization_url, sign_oauth_state

logger = logging.getLogger(__name__)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _owner_names(
    given_name: str | None,
    family_name: str | None,
    display_name: str | None,
) -> tuple[str, str] | None:
    given = _clean(given_name)
    family = _clean(family_name)
    if given and family:
        return given, family

    display = _clean(display_name)
    if not display:
        return None
    parts = display.split(" ", 1)
    if len(parts) != 2 or not parts[1].strip():
        return None
    return given or parts[0], family or parts[1].strip()


def build_client_link_prefill(
    *,
    email: str | None,
    display_name: str | None,
    organization_name: str | None,
    locale: str | None,
    country: str | None,
    given_name: str | None = None,
    family_name: str | None = None,
    street_and_number: str | None = None,
    postal_code: str | None = None,
    city: str | None = None,
    region: str | None = None,
    registration_number: str | None = None,
    vat_number: str | None = None,
) -> dict[str, Any] | None:
    """Build Mollie Client Link data when enough reliable customer data exists.

    Client Links require owner names, email, organization name and country. Missing
    optional data is intentionally omitted; Mollie collects it during onboarding.
    If the minimum cannot be derived safely, the caller falls back to plain OAuth.
    """

    owner_names = _owner_names(given_name, family_name, display_name)
    owner_email = _clean(email)
    company_name = _clean(organization_name)
    country_code = (_clean(country) or "").upper()
    if not owner_names or not owner_email or not company_name:
        return None
    if len(country_code) != 2 or not country_code.isalpha():
        return None

    owner: dict[str, str] = {
        "email": owner_email,
        "givenName": owner_names[0],
        "familyName": owner_names[1],
    }
    normalized_locale = normalize_locale(locale)
    if normalized_locale:
        owner["locale"] = normalized_locale

    address: dict[str, str] = {"country": country_code}
    optional_address = {
        "streetAndNumber": street_and_number,
        "postalCode": postal_code,
        "city": city,
        "region": region,
    }
    for key, value in optional_address.items():
        cleaned = _clean(value)
        if cleaned:
            address[key] = cleaned

    payload: dict[str, Any] = {
        "owner": owner,
        "name": company_name,
        "address": address,
    }
    registration = _clean(registration_number)
    vat = _clean(vat_number)
    if registration:
        payload["registrationNumber"] = registration
    if vat:
        payload["vatNumber"] = vat
    return payload


def client_link_redirect_url(client_link_url: str, organization_id: str) -> str:
    query = urlencode(
        {
            "client_id": settings.mollie_oauth_client_id,
            "state": sign_oauth_state(organization_id),
            "approval_prompt": "auto",
            "scope": settings.mollie_oauth_scopes,
        }
    )
    separator = "&" if "?" in client_link_url else "?"
    return f"{client_link_url}{separator}{query}"


async def onboarding_authorization_url(
    organization_id: str,
    prefill: dict[str, Any] | None,
) -> str:
    """Return the best available Mollie onboarding URL.

    The normal OAuth URL is always usable when Mollie Connect is configured. If an
    optional Advanced access token and sufficient customer data are available, a
    Client Link is created first so Mollie can prefill registration/onboarding. A
    Client Link failure never blocks connecting an existing or new Mollie account.
    """

    fallback_url = oauth_authorization_url(organization_id)
    access_token = settings.mollie_connect_access_token.strip()
    if not access_token or prefill is None:
        return fallback_url

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{settings.mollie_api_url.rstrip('/')}/client-links",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/hal+json",
                },
                json=prefill,
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected Mollie Client Link response")
        client_link_url = str(
            (((payload.get("_links") or {}).get("clientLink") or {}).get("href") or "")
        ).strip()
        if not client_link_url:
            raise ValueError("Mollie Client Link response did not contain a URL")
        return client_link_redirect_url(client_link_url, organization_id)
    except (httpx.HTTPError, ValueError, TypeError):
        logger.warning(
            "Mollie Client Link creation failed; falling back to standard OAuth",
            exc_info=True,
        )
        return fallback_url
