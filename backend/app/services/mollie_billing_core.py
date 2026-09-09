from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.billing_catalog import PRO_YEARLY_TARIFF
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.billing import (
    BillingCycle,
    BillingInvoice,
    BillingLegalEntity,
    BillingPaymentTransaction,
    BillingProfile,
    BillingTaxRegistration,
)
from app.models.entities import Organization
from app.models.platform import StoreSubscription
from app.services.billing import (
    PRO_PRODUCT_ID,
    VerifiedSubscription,
    apply_verified_subscription,
    purchase_context,
)
from app.services.billing_invoice_copy import billing_invoice_copy
from app.services.billing_tax import TaxDecision, tax_decision
from app.services.secrets import decrypt_config, encrypt_config

logger = logging.getLogger(__name__)

MOLLIE_PROVIDER = "mollie"
MOLLIE_INTERVAL = PRO_YEARLY_TARIFF.interval
MOLLIE_PURPOSE = "zahlmeister_pro_subscription"
MOLLIE_GRACE_DAYS = max(1, int(os.getenv("MOLLIE_BILLING_GRACE_DAYS", "7")))
MAX_PAYMENT_RECOVERY_PAGES = max(1, int(os.getenv("MOLLIE_BILLING_RECOVERY_MAX_PAGES", "100")))
MAX_INVOICE_RECOVERY_PAGES = MAX_PAYMENT_RECOVERY_PAGES
MAX_RENEWAL_RETRIES = max(1, int(os.getenv("MOLLIE_BILLING_MAX_RETRIES", "3")))
OPEN_PAYMENT_STATUSES = {"open", "pending"}
FAILED_PAYMENT_STATUSES = {"failed", "canceled", "cancelled", "expired"}
USABLE_MANDATE_STATUSES = {"valid"}
OPEN_INVOICE_STATUSES = {
    "creating",
    "pending-payment",
    "issued",
    "overdue",
    "payment-reversed",
    "payment_reversed",
}


class MollieBillingError(RuntimeError):
    pass


class MollieBillingUnavailable(MollieBillingError):
    pass


class MollieBillingConflict(MollieBillingError):
    pass


class MollieBillingVerificationError(MollieBillingError):
    pass


class MollieBillingProfileRequired(MollieBillingError):
    pass


@dataclass(frozen=True)
class MollieCheckout:
    checkout_url: str
    payment_id: str
    resumed: bool


def amount_value() -> str:
    return _decimal_amount(settings.mollie_billing_pro_yearly_amount)


def billing_config() -> dict[str, object]:
    return {
        "available": billing_configured(),
        "product_id": PRO_PRODUCT_ID,
        "amount": amount_value() if settings.mollie_billing_pro_yearly_amount > 0 else "",
        "currency": settings.mollie_billing_currency.strip().upper(),
        "interval": MOLLIE_INTERVAL,
        "environment": settings.mollie_billing_environment,
    }


def billing_configured() -> bool:
    if not settings.mollie_billing_configured:
        return False
    key = settings.mollie_billing_api_key.strip()
    if settings.mollie_billing_environment == "test":
        return key.startswith("test_")
    return key.startswith("live_")


def billing_readiness_errors() -> list[str]:
    if not billing_configured():
        return ["mollie_billing_not_configured"]
    errors: list[str] = []
    if settings.mollie_billing_environment == "live":
        if len(settings.mollie_billing_webhook_secret.strip()) < 32:
            errors.append("mollie_invoice_webhook_secret_missing")
        required = {
            "BILLING_SELLER_LEGAL_NAME": os.getenv("BILLING_SELLER_LEGAL_NAME", ""),
            "BILLING_SELLER_COUNTRY": os.getenv("BILLING_SELLER_COUNTRY", ""),
            "BILLING_SELLER_EMAIL": os.getenv("BILLING_SELLER_EMAIL", ""),
            "BILLING_SELLER_STREET_AND_NUMBER": os.getenv("BILLING_SELLER_STREET_AND_NUMBER", ""),
            "BILLING_SELLER_POSTAL_CODE": os.getenv("BILLING_SELLER_POSTAL_CODE", ""),
            "BILLING_SELLER_CITY": os.getenv("BILLING_SELLER_CITY", ""),
        }
        errors.extend(
            f"{key.lower()}_missing" for key, value in required.items() if not value.strip()
        )
        country = os.getenv("BILLING_SELLER_COUNTRY", "").strip().upper()
        if country and len(country) != 2:
            errors.append("billing_seller_country_invalid")
        if not (
            os.getenv("BILLING_SELLER_VAT_NUMBER", "").strip()
            or os.getenv("BILLING_SELLER_ORGANIZATION_NUMBER", "").strip()
        ):
            errors.append("billing_seller_tax_identifier_missing")
    return errors


def _require_configured() -> None:
    if not billing_configured():
        raise MollieBillingUnavailable("Mollie billing is not configured")
    if settings.mollie_billing_environment == "live":
        errors = billing_readiness_errors()
        if errors:
            raise MollieBillingUnavailable("Mollie billing is not ready for live use")


def _decimal_amount(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _vat_rate_value(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _current_billing_terms() -> tuple[str, str]:
    return amount_value(), settings.mollie_billing_currency.strip().upper()


def _stored_billing_terms(data: dict[str, Any]) -> tuple[str, str]:
    amount = data.get("billing_amount")
    currency = data.get("billing_currency")
    if isinstance(amount, str) and isinstance(currency, str) and len(currency.strip()) == 3:
        return amount, currency.strip().upper()
    return _current_billing_terms()


def _metadata(organization_id: UUID) -> dict[str, str]:
    return {
        "purpose": MOLLIE_PURPOSE,
        "organization_id": str(organization_id),
        "product_id": PRO_PRODUCT_ID,
    }


def _payment_metadata(
    organization_id: UUID,
    cycle: BillingCycle,
    transaction: BillingPaymentTransaction,
) -> dict[str, str]:
    return {
        **_metadata(organization_id),
        "billing_key": cycle.billing_key,
        "billing_cycle_id": str(cycle.id),
        "payment_transaction_id": str(transaction.id),
    }


def _webhook_url() -> str | None:
    base = settings.oauth_callback_base
    parsed = urlparse(base)
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if settings.environment == "production" and parsed.scheme != "https":
        return None
    return f"{base}/api/v1/billing/mollie/webhook"


def _return_url(result: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/app?view=billing&billing={result}"


def _add_year(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, month=2, day=28)


def _add_year_datetime(value: datetime) -> datetime:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, month=2, day=28)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _normalize_sales_invoice_status(value: Any) -> str:
    status = str(value or "creating").strip().lower()
    if status == "payment_reversed":
        return "payment-reversed"
    if status == "canceled":
        return "cancelled"
    return status


def _invoice_reference(item: BillingInvoice) -> str:
    return f"ZM:{item.id}"


def _reference_invoice_id(payload: dict[str, Any]) -> UUID | None:
    memo = payload.get("memo")
    if not isinstance(memo, str):
        return None
    for line in memo.splitlines():
        value = line.strip()
        if value.startswith("ZM:"):
            try:
                return UUID(value.removeprefix("ZM:").strip())
            except ValueError:
                return None
    return None


def _payment_amount_matches(
    payment: dict[str, Any],
    expected_amount: str | None = None,
    expected_currency: str | None = None,
) -> bool:
    amount = payment.get("amount")
    if not isinstance(amount, dict):
        return False
    configured_amount, configured_currency = _current_billing_terms()
    wanted_amount = expected_amount or configured_amount
    wanted_currency = (expected_currency or configured_currency).upper()
    if str(amount.get("currency", "")).upper() != wanted_currency:
        return False
    try:
        return Decimal(str(amount.get("value", ""))) == Decimal(wanted_amount)
    except InvalidOperation:
        return False


def _verified_metadata(payment: dict[str, Any]) -> UUID:
    metadata = payment.get("metadata")
    if not isinstance(metadata, dict):
        raise MollieBillingVerificationError("Mollie payment metadata is missing")
    if metadata.get("purpose") != MOLLIE_PURPOSE or metadata.get("product_id") != PRO_PRODUCT_ID:
        raise MollieBillingVerificationError("Mollie payment metadata is invalid")
    try:
        return UUID(str(metadata.get("organization_id")))
    except (TypeError, ValueError) as exc:
        raise MollieBillingVerificationError("Mollie payment account binding is invalid") from exc


def _grace_expiry(
    data: dict[str, Any],
    paid_through: datetime | None,
    *,
    now: datetime | None = None,
) -> datetime:
    existing = _parse_datetime(data.get("grace_until"))
    if existing is not None:
        return existing
    current = now or datetime.now(UTC)
    base = _normalize_utc(paid_through or current)
    grace_until = base + timedelta(days=MOLLIE_GRACE_DAYS)
    data["grace_until"] = grace_until.isoformat()
    return grace_until


async def _request_json(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    _require_configured()
    headers = {
        "Authorization": f"Bearer {settings.mollie_billing_api_key.strip()}",
        "Accept": "application/hal+json",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    url = f"{settings.mollie_api_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(method, url, headers=headers, json=json_body, params=params)
    except httpx.HTTPError as exc:
        raise MollieBillingUnavailable("Mollie billing is unavailable") from exc
    if response.status_code >= 400:
        logger.warning(
            "Mollie billing request failed: method=%s path=%s status=%s",
            method,
            path,
            response.status_code,
        )
        raise MollieBillingUnavailable("Mollie billing is unavailable")
    if response.status_code == 204 or not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        raise MollieBillingUnavailable("Mollie returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise MollieBillingUnavailable("Mollie returned an invalid response")
    return payload


async def _get_payment(payment_id: str) -> dict[str, Any]:
    return await _request_json("GET", f"payments/{payment_id}")


async def _get_sales_invoice(invoice_id: str) -> dict[str, Any]:
    return await _request_json("GET", f"sales-invoices/{invoice_id}")


def _checkout_url(payment: dict[str, Any]) -> str | None:
    links = payment.get("_links")
    checkout = links.get("checkout") if isinstance(links, dict) else None
    href = checkout.get("href") if isinstance(checkout, dict) else None
    return href if isinstance(href, str) and href.startswith("https://") else None


def _verification_data(subscription: StoreSubscription) -> dict[str, Any]:
    return decrypt_config(subscription.verification_data_encrypted)


async def _mollie_row(
    session: AsyncSession,
    organization_id: UUID,
    *,
    lock: bool = False,
) -> StoreSubscription | None:
    statement = select(StoreSubscription).where(
        StoreSubscription.organization_id == organization_id,
        StoreSubscription.provider == MOLLIE_PROVIDER,
    )
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


def _mollie_locale(locale: str) -> str | None:
    normalized = locale.replace("-", "_")
    supported = {
        "cs_CZ", "da_DK", "de_AT", "de_CH", "de_DE", "de_LU", "en_BE", "en_GB",
        "en_NL", "en_US", "es_ES", "fi_FI", "fr_BE", "fr_FR", "fr_LU", "hu_HU",
        "is_IS", "it_IT", "lt_LT", "lv_LV", "nb_NO", "nl_BE", "nl_NL", "pl_PL",
        "pt_PT", "sk_SK", "sv_SE",
    }
    if normalized in supported:
        return normalized
    language = normalized.split("_")[0].lower()
    return {
        "de": "de_AT", "en": "en_GB", "fr": "fr_FR", "es": "es_ES", "it": "it_IT",
        "nl": "nl_NL", "pt": "pt_PT", "pl": "pl_PL", "cs": "cs_CZ", "da": "da_DK",
        "fi": "fi_FI", "hu": "hu_HU", "lt": "lt_LT", "lv": "lv_LV", "sk": "sk_SK",
        "sv": "sv_SE",
    }.get(language)


def _customer_name(profile: BillingProfile) -> str:
    if profile.customer_type == "business" and profile.organization_name:
        return profile.organization_name
    return " ".join(item for item in (profile.given_name, profile.family_name) if item).strip()


def _billing_address(profile: BillingProfile) -> dict[str, str]:
    payload: dict[str, str] = {
        "email": profile.billing_email,
        "streetAndNumber": profile.street_and_number,
        "city": profile.city,
        "country": profile.country,
    }
    if profile.postal_code:
        payload["postalCode"] = profile.postal_code
    if profile.region:
        payload["region"] = profile.region
    if profile.customer_type == "consumer":
        if profile.given_name:
            payload["givenName"] = profile.given_name
        if profile.family_name:
            payload["familyName"] = profile.family_name
    elif profile.organization_name:
        payload["organizationName"] = profile.organization_name
    return payload


def _invoice_recipient(profile: BillingProfile) -> dict[str, str]:
    payload = {
        "type": profile.customer_type,
        "email": profile.billing_email,
        "streetAndNumber": profile.street_and_number,
        "city": profile.city,
        "country": profile.country,
    }
    if profile.postal_code:
        payload["postalCode"] = profile.postal_code
    if profile.region:
        payload["region"] = profile.region
    if profile.customer_type == "business":
        if not profile.organization_name:
            raise MollieBillingProfileRequired("Business billing requires an organization name")
        if not profile.vat_number and not profile.organization_number:
            raise MollieBillingProfileRequired("Business billing requires a VAT number or organization number")
        payload["organizationName"] = profile.organization_name
        if profile.vat_number:
            payload["vatNumber"] = profile.vat_number.replace(" ", "").upper()
        if profile.organization_number:
            payload["organizationNumber"] = profile.organization_number
    else:
        if not profile.given_name or not profile.family_name:
            raise MollieBillingProfileRequired("Consumer billing requires first and family name")
        payload["givenName"] = profile.given_name
        payload["familyName"] = profile.family_name
    return payload


def _tax_snapshot(decision: TaxDecision) -> dict[str, str]:
    return {
        "billing_tax_rate": _vat_rate_value(decision.rate),
        "billing_vat_scheme": decision.vat_scheme,
        "billing_tax_treatment": decision.treatment,
        "billing_tax_rule_version": decision.rule_version,
    }


async def _load_profile(session: AsyncSession, organization_id: UUID) -> BillingProfile:
    profile = await session.get(BillingProfile, organization_id)
    if profile is None:
        raise MollieBillingProfileRequired("Billing details are required before activating Pro")
    return profile


async def _prepare_profile_tax(profile: BillingProfile) -> TaxDecision:
    decision = await tax_decision(profile)
    if decision.vat_scheme == "one-stop-shop" and os.getenv("BILLING_SELLER_EU_OSS_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        raise MollieBillingProfileRequired("EU OSS billing is required for this customer but is not enabled")
    profile.vat_validation_status = decision.vat_validation_status
    profile.vat_validated_at = decision.vat_validated_at
    return decision


async def _ensure_customer(
    organization_id: UUID,
    profile: BillingProfile,
    organization_locale: str,
    data: dict[str, Any],
) -> str:
    payload: dict[str, Any] = {"name": _customer_name(profile)[:255], "email": profile.billing_email}
    locale = _mollie_locale(organization_locale)
    if locale:
        payload["locale"] = locale
    existing = data.get("mollie_customer_id")
    if isinstance(existing, str) and existing.startswith("cst_"):
        await _request_json("PATCH", f"customers/{existing}", json_body=payload)
        return existing
    payload["metadata"] = {"purpose": "zahlmeister_billing_customer", "organization_id": str(organization_id)}
    customer = await _request_json(
        "POST",
        "customers",
        json_body=payload,
        idempotency_key=f"zahlmeister-customer-{organization_id}",
    )
    customer_id = customer.get("id")
    if not isinstance(customer_id, str) or not customer_id.startswith("cst_"):
        raise MollieBillingUnavailable("Mollie customer creation failed")
    return customer_id


def _reset_finished_subscription_data(data: dict[str, Any]) -> None:
    for key in (
        "subscription_id", "mandate_id", "subscription_status", "initial_payment_id",
        "checkout_url", "checkout_attempt", "last_payment_id", "last_payment_status",
        "billing_amount", "billing_currency", "billing_tariff_version", "billing_recipient",
        "billing_tax_rate", "billing_vat_scheme", "billing_tax_treatment",
        "billing_tax_rule_version", "latest_invoice_id", "paid_through", "grace_until",
    ):
        data.pop(key, None)


def _seller_values() -> dict[str, str | None]:
    return {
        "code": "platform",
        "legal_name": os.getenv("BILLING_SELLER_LEGAL_NAME", "").strip() or None,
        "country": os.getenv("BILLING_SELLER_COUNTRY", "").strip().upper() or None,
        "billing_email": os.getenv("BILLING_SELLER_EMAIL", "").strip() or None,
        "street_and_number": os.getenv("BILLING_SELLER_STREET_AND_NUMBER", "").strip() or None,
        "postal_code": os.getenv("BILLING_SELLER_POSTAL_CODE", "").strip() or None,
        "city": os.getenv("BILLING_SELLER_CITY", "").strip() or None,
        "region": os.getenv("BILLING_SELLER_REGION", "").strip() or None,
        "vat_number": os.getenv("BILLING_SELLER_VAT_NUMBER", "").replace(" ", "").upper() or None,
        "organization_number": os.getenv("BILLING_SELLER_ORGANIZATION_NUMBER", "").strip() or None,
        "mollie_profile_id": os.getenv("BILLING_SELLER_MOLLIE_PROFILE_ID", "").strip() or None,
    }


async def _ensure_legal_entity(session: AsyncSession) -> BillingLegalEntity | None:
    values = _seller_values()
    required = ("legal_name", "country", "billing_email", "street_and_number", "postal_code", "city")
    if any(not values[key] for key in required):
        if settings.mollie_billing_environment == "live":
            raise MollieBillingUnavailable("Billing seller identity is incomplete")
        return None
    item = await session.scalar(
        select(BillingLegalEntity).where(BillingLegalEntity.code == "platform").with_for_update()
    )
    if item is None:
        item = BillingLegalEntity(
            code="platform",
            legal_name=str(values["legal_name"]),
            country=str(values["country"]),
            billing_email=str(values["billing_email"]),
            street_and_number=str(values["street_and_number"]),
            postal_code=str(values["postal_code"]),
            city=str(values["city"]),
        )
        session.add(item)
        await session.flush()
    for key in (
        "legal_name", "country", "billing_email", "street_and_number", "postal_code", "city",
        "region", "vat_number", "organization_number", "mollie_profile_id",
    ):
        setattr(item, key, values[key])
    item.active = True
    await session.flush()

    if item.vat_number:
        registration = await session.scalar(
            select(BillingTaxRegistration).where(
                BillingTaxRegistration.legal_entity_id == item.id,
                BillingTaxRegistration.registration_type == "vat",
                BillingTaxRegistration.country == item.country,
            ).with_for_update()
        )
        if registration is None:
            session.add(BillingTaxRegistration(
                legal_entity_id=item.id,
                registration_type="vat",
                country=item.country,
                registration_reference=item.vat_number,
                active=True,
            ))
        else:
            registration.registration_reference = item.vat_number
            registration.active = True
    if os.getenv("BILLING_SELLER_EU_OSS_ENABLED", "false").lower() in {"1", "true", "yes"}:
        oss = await session.scalar(
            select(BillingTaxRegistration).where(
                BillingTaxRegistration.legal_entity_id == item.id,
                BillingTaxRegistration.registration_type == "eu_oss",
                BillingTaxRegistration.country == item.country,
            ).with_for_update()
        )
        if oss is None:
            session.add(BillingTaxRegistration(
                legal_entity_id=item.id,
                registration_type="eu_oss",
                country=item.country,
                registration_reference=item.vat_number,
                active=True,
            ))
        else:
            oss.active = True
    return item


def _invoice_amounts(gross: Decimal, vat_rate: Decimal) -> tuple[Decimal, Decimal]:
    if vat_rate == 0:
        return gross.quantize(Decimal("0.01")), Decimal("0.00")
    divisor = Decimal("1") + vat_rate / Decimal("100")
    net = (gross / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return net, (gross - net).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _invoice_record(
    session: AsyncSession,
    cycle: BillingCycle,
    transaction: BillingPaymentTransaction,
    *,
    source_payment_id: str,
) -> BillingInvoice:
    existing = await session.scalar(
        select(BillingInvoice).where(BillingInvoice.billing_cycle_id == cycle.id).with_for_update()
    )
    if existing is not None:
        return existing
    recipient = json.loads(cycle.recipient_json)
    seller = await _ensure_legal_entity(session)
    net, tax = _invoice_amounts(Decimal(cycle.gross_amount), Decimal(cycle.tax_rate))
    item = BillingInvoice(
        organization_id=cycle.organization_id,
        billing_cycle_id=cycle.id,
        payment_transaction_id=transaction.id,
        provider=MOLLIE_PROVIDER,
        product_id=cycle.product_id,
        tariff_version=cycle.tariff_version,
        period_start=cycle.period_start,
        period_end=cycle.period_end,
        net_amount=net,
        tax_amount=tax,
        gross_amount=cycle.gross_amount,
        currency=cycle.currency,
        vat_rate=cycle.tax_rate,
        vat_scheme=cycle.tax_scheme,
        tax_treatment=cycle.tax_treatment,
        recipient_country=str(recipient["country"]),
        recipient_type=str(recipient["type"]),
        recipient_vat_number=recipient.get("vatNumber"),
        seller_legal_name=seller.legal_name if seller else None,
        seller_country=seller.country if seller else None,
        seller_vat_number=seller.vat_number if seller else None,
        status="creating",
        payment_reference=source_payment_id,
        details_json=json.dumps(
            {
                "kind": f"{cycle.operation}_receipt",
                "tax_rule_version": cycle.tax_rule_version,
                "recipient": recipient,
                "source_payment_id": source_payment_id,
                "billing_key": cycle.billing_key,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    session.add(item)
    await session.flush()
    return item


def _invoice_details(item: BillingInvoice) -> dict[str, Any]:
    try:
        value = json.loads(item.details_json or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _remote_invoice_matches_local(item: BillingInvoice, payload: dict[str, Any]) -> bool:
    if payload.get("recipientIdentifier") != f"zahlmeister-{item.organization_id}":
        return False
    if _reference_invoice_id(payload) != item.id:
        return False
    mode = payload.get("mode")
    if mode is not None and str(mode) != settings.mollie_billing_environment:
        return False
    if payload.get("vatScheme") not in {None, item.vat_scheme}:
        return False
    if payload.get("currency") not in {None, item.currency}:
        return False
    recipient = payload.get("recipient")
    if isinstance(recipient, dict):
        if recipient.get("type") not in {None, item.recipient_type}:
            return False
        if recipient.get("country") not in {None, item.recipient_country}:
            return False
    lines = payload.get("lines")
    if not isinstance(lines, list) or len(lines) != 1 or not isinstance(lines[0], dict):
        return False
    line = lines[0]
    if line.get("quantity") not in {1, "1", "1.0"}:
        return False
    try:
        remote_vat_rate = Decimal(str(line.get("vatRate", "")))
        remote_amount = Decimal(str((line.get("unitPrice") or {}).get("value", "")))
    except (InvalidOperation, AttributeError):
        return False
    unit_price = line.get("unitPrice")
    return (
        remote_vat_rate == Decimal(item.vat_rate)
        and isinstance(unit_price, dict)
        and str(unit_price.get("currency", "")).upper() == item.currency.upper()
        and remote_amount == Decimal(item.gross_amount)
    )


def _embedded_rows(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    embedded = payload.get("_embedded")
    if not isinstance(embedded, dict):
        raise MollieBillingUnavailable("Mollie list response is invalid")
    for key in keys:
        rows = embedded.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    raise MollieBillingUnavailable("Mollie list response is invalid")


def _next_cursor(payload: dict[str, Any]) -> str | None:
    links = payload.get("_links")
    next_link = links.get("next") if isinstance(links, dict) else None
    href = next_link.get("href") if isinstance(next_link, dict) else None
    if not isinstance(href, str) or not href:
        return None
    values = parse_qs(urlparse(href).query).get("from")
    return values[0] if values and values[0] else None


async def _find_remote_payment(
    transaction: BillingPaymentTransaction,
    cycle: BillingCycle,
    customer_id: str,
) -> dict[str, Any] | None:
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(MAX_PAYMENT_RECOVERY_PAGES):
        params: dict[str, Any] = {"limit": 250}
        if cursor:
            params["from"] = cursor
        payload = await _request_json("GET", f"customers/{customer_id}/payments", params=params)
        for remote in _embedded_rows(payload, ("payments",)):
            metadata = remote.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if (
                metadata.get("billing_key") != cycle.billing_key
                or metadata.get("billing_cycle_id") != str(cycle.id)
                or metadata.get("payment_transaction_id") != str(transaction.id)
            ):
                continue
            if not _payment_amount_matches(remote, _decimal_amount(transaction.gross_amount), transaction.currency):
                raise MollieBillingVerificationError("Recovered Mollie payment amount does not match")
            if str(remote.get("sequenceType", "")) != transaction.sequence_type:
                raise MollieBillingVerificationError("Recovered Mollie payment sequence does not match")
            if remote.get("customerId") not in {None, customer_id}:
                raise MollieBillingVerificationError("Recovered Mollie payment customer does not match")
            return remote
        next_cursor = _next_cursor(payload)
        if next_cursor is None:
            return None
        if next_cursor in seen:
            raise MollieBillingUnavailable("Mollie payment pagination did not advance")
        seen.add(next_cursor)
        cursor = next_cursor
    raise MollieBillingUnavailable("Mollie payment recovery scan is incomplete")


async def _find_remote_invoice(item: BillingInvoice) -> dict[str, Any] | None:
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(MAX_INVOICE_RECOVERY_PAGES):
        params: dict[str, Any] = {"limit": 250}
        if cursor:
            params["from"] = cursor
        payload = await _request_json("GET", "sales-invoices", params=params)
        for remote in _embedded_rows(payload, ("salesInvoices", "sales-invoices", "sales_invoices", "invoices")):
            if _reference_invoice_id(remote) != item.id:
                continue
            if not _remote_invoice_matches_local(item, remote):
                raise MollieBillingVerificationError("Recovered Mollie invoice does not match local billing data")
            return remote
        next_cursor = _next_cursor(payload)
        if next_cursor is None:
            return None
        if next_cursor in seen:
            raise MollieBillingUnavailable("Mollie sales invoice pagination did not advance")
        seen.add(next_cursor)
        cursor = next_cursor
    raise MollieBillingUnavailable("Mollie sales invoice recovery scan is incomplete")


async def _create_remote_receipt(item: BillingInvoice, locale: str) -> dict[str, Any]:
    details = _invoice_details(item)
    recipient = details.get("recipient")
    if not isinstance(recipient, dict):
        raise MollieBillingVerificationError("Billing invoice recipient snapshot is missing")
    copy = billing_invoice_copy(locale)
    memo = [copy.reverse_charge_memo] if item.tax_treatment == "eu_reverse_charge" else []
    memo.append(_invoice_reference(item))
    payload: dict[str, Any] = {
        "status": "paid",
        "vatScheme": item.vat_scheme,
        "vatMode": "inclusive",
        "memo": "\n".join(memo),
        "recipientIdentifier": f"zahlmeister-{item.organization_id}",
        "recipient": recipient,
        "paymentDetails": {"source": "manual"},
        "lines": [{
            "description": copy.line_description,
            "quantity": 1,
            "vatRate": _vat_rate_value(item.vat_rate),
            "unitPrice": {"currency": item.currency, "value": _decimal_amount(item.gross_amount)},
        }],
        "emailDetails": {"subject": copy.email_subject, "body": copy.email_body},
    }
    profile_id = os.getenv("BILLING_SELLER_MOLLIE_PROFILE_ID", "").strip()
    if profile_id:
        payload["profileId"] = profile_id
    return await _request_json(
        "POST",
        "sales-invoices",
        json_body=payload,
        idempotency_key=f"zahlmeister-invoice-{item.idempotency_key}",
    )


async def _apply_invoice_payload(session: AsyncSession, item: BillingInvoice, payload: dict[str, Any]) -> None:
    remote_id = payload.get("id")
    if not isinstance(remote_id, str) or not remote_id.startswith("invoice_"):
        raise MollieBillingVerificationError("Mollie sales invoice reference is invalid")
    if item.external_id and item.external_id != remote_id:
        raise MollieBillingVerificationError("Mollie sales invoice binding changed unexpectedly")
    if payload.get("recipientIdentifier") not in {None, f"zahlmeister-{item.organization_id}"}:
        raise MollieBillingVerificationError("Mollie sales invoice belongs to another account")
    memo = payload.get("memo")
    if isinstance(memo, str) and "ZM:" in memo and _invoice_reference(item) not in memo:
        raise MollieBillingVerificationError("Mollie sales invoice local reference is invalid")
    item.external_id = remote_id
    item.invoice_number = str(payload.get("invoiceNumber")) if payload.get("invoiceNumber") else None
    item.status = _normalize_sales_invoice_status(payload.get("status"))
    item.payment_url = None
    item.last_synced_at = datetime.now(UTC)
    if item.status == "paid":
        item.paid_at = _parse_datetime(payload.get("paidAt")) or item.paid_at or datetime.now(UTC)

    # Compatibility only: invoices created by the pre-v2 renewal flow could still be
    # the payment-producing object. New v2 receipts never drive entitlements.
    if item.billing_cycle_id is None and _invoice_details(item).get("kind") == "renewal" and item.status == "paid":
        row = await _mollie_row(session, item.organization_id, lock=True)
        if row is not None:
            data = _verification_data(row)
            data["paid_through"] = item.period_end.isoformat()
            data["latest_invoice_id"] = item.external_id
            await apply_verified_subscription(
                session,
                item.organization_id,
                VerifiedSubscription(
                    provider=MOLLIE_PROVIDER,
                    product_id=PRO_PRODUCT_ID,
                    external_reference=str(data.get("mandate_id") or item.external_id),
                    account_token=str(item.organization_id),
                    status="active",
                    purchased_at=row.purchased_at or item.period_start,
                    expires_at=item.period_end,
                    auto_renew=bool(row.auto_renew),
                    environment=settings.mollie_billing_environment,
                    verification_data=data,
                ),
            )


async def _ensure_receipt(invoice_id: UUID) -> None:
    async with SessionLocal.begin() as session:
        item = await session.get(BillingInvoice, invoice_id, with_for_update=True)
        if item is None:
            return
        if item.external_id:
            remote_id = item.external_id
        else:
            remote_id = None
        organization = await session.get(Organization, item.organization_id)
        locale = organization.locale if organization else "en"

    if remote_id:
        payload = await _get_sales_invoice(remote_id)
    else:
        async with SessionLocal() as session:
            probe = await session.get(BillingInvoice, invoice_id)
            if probe is None:
                return
            payload = await _find_remote_invoice(probe)
        if payload is None:
            async with SessionLocal() as session:
                probe = await session.get(BillingInvoice, invoice_id)
                if probe is None:
                    return
                payload = await _create_remote_receipt(probe, locale)

    async with SessionLocal.begin() as session:
        item = await session.get(BillingInvoice, invoice_id, with_for_update=True)
        if item is not None:
            if not _remote_invoice_matches_local(item, payload):
                raise MollieBillingVerificationError("Mollie sales invoice does not match local billing data")
            await _apply_invoice_payload(session, item, payload)


async def _valid_mandate(customer_id: str, preferred_id: str | None = None) -> str:
    if preferred_id:
        mandate = await _request_json("GET", f"customers/{customer_id}/mandates/{preferred_id}")
        if mandate.get("status") == "valid":
            return preferred_id
    payload = await _request_json("GET", f"customers/{customer_id}/mandates")
    mandates = _embedded_rows(payload, ("mandates",))
    match = next((row for row in mandates if row.get("status") in USABLE_MANDATE_STATUSES), None)
    mandate_id = match.get("id") if match else None
    if not isinstance(mandate_id, str):
        raise MollieBillingUnavailable("Mollie mandate is not ready")
    return mandate_id


def _remote_payment_status(value: Any) -> str:
    status = str(value or "pending").lower()
    return "cancelled" if status == "canceled" else status


async def _process_payment_payload(payment: dict[str, Any]) -> UUID:
    organization_id = _verified_metadata(payment)
    payment_id = payment.get("id")
    metadata = payment.get("metadata")
    if not isinstance(payment_id, str) or not payment_id.startswith("tr_") or not isinstance(metadata, dict):
        raise MollieBillingVerificationError("Mollie payment reference is invalid")
    try:
        cycle_id = UUID(str(metadata["billing_cycle_id"]))
        transaction_id = UUID(str(metadata["payment_transaction_id"]))
    except (KeyError, ValueError) as exc:
        # Legacy first/subscription payments are handled below.
        return await _process_legacy_payment_payload(payment)

    sequence_type = str(payment.get("sequenceType", ""))
    mandate_id: str | None = None
    if _remote_payment_status(payment.get("status")) == "paid" and sequence_type == "first":
        customer_id = payment.get("customerId")
        if not isinstance(customer_id, str):
            raise MollieBillingVerificationError("Mollie customer is missing")
        mandate_id = await _valid_mandate(customer_id)

    invoice_id: UUID | None = None
    async with SessionLocal.begin() as session:
        row = await _mollie_row(session, organization_id, lock=True)
        if row is None:
            raise MollieBillingVerificationError("Mollie payment is not linked to a subscription")
        cycle = await session.get(BillingCycle, cycle_id, with_for_update=True)
        if cycle is None or cycle.organization_id != organization_id:
            raise MollieBillingVerificationError("Mollie billing cycle binding is invalid")
        transaction = await session.get(BillingPaymentTransaction, transaction_id, with_for_update=True)
        if transaction is None or transaction.cycle_id != cycle.id or transaction.organization_id != organization_id:
            raise MollieBillingVerificationError("Mollie payment transaction binding is invalid")
        if metadata.get("billing_key") != cycle.billing_key:
            raise MollieBillingVerificationError("Mollie billing key is invalid")
        if transaction.provider_reference and transaction.provider_reference != payment_id:
            raise MollieBillingVerificationError("Mollie payment binding changed unexpectedly")
        if not _payment_amount_matches(payment, _decimal_amount(transaction.gross_amount), transaction.currency):
            raise MollieBillingVerificationError("Mollie payment amount does not match the billing cycle")
        if sequence_type != transaction.sequence_type:
            raise MollieBillingVerificationError("Mollie payment sequence does not match the billing cycle")
        if payment.get("mode") not in {None, transaction.provider_environment}:
            raise MollieBillingVerificationError("Mollie payment environment does not match")

        data = _verification_data(row)
        customer_id = data.get("mollie_customer_id")
        if payment.get("customerId") not in {None, customer_id}:
            raise MollieBillingVerificationError("Mollie customer does not match the subscription")

        status = _remote_payment_status(payment.get("status"))
        transaction.provider_reference = payment_id
        transaction.status = status if status in {"open", "pending", "paid", "failed", "cancelled", "expired"} else "pending"
        transaction.last_synced_at = datetime.now(UTC)
        transaction.last_error = None
        row.last_verified_at = datetime.now(UTC)
        data.update({"last_payment_id": payment_id, "last_payment_status": status})

        if status == "paid":
            paid_at = _parse_datetime(payment.get("paidAt")) or datetime.now(UTC)
            transaction.paid_at = paid_at
            cycle.status = "paid"
            if cycle.operation == "initial":
                cycle.period_start = paid_at
                cycle.period_end = _add_year_datetime(paid_at)
                if mandate_id is None:
                    raise MollieBillingUnavailable("Mollie mandate is not ready")
                data["mandate_id"] = mandate_id
            data["paid_through"] = cycle.period_end.isoformat()
            data.pop("grace_until", None)
            data["billing_flow_version"] = 2
            invoice = await _invoice_record(session, cycle, transaction, source_payment_id=payment_id)
            invoice_id = invoice.id
            auto_renew = bool(row.auto_renew) if row.cancelled_at else True
            reference = str(data.get("mandate_id") or payment_id)
            await apply_verified_subscription(
                session,
                organization_id,
                VerifiedSubscription(
                    provider=MOLLIE_PROVIDER,
                    product_id=PRO_PRODUCT_ID,
                    external_reference=reference,
                    account_token=str(organization_id),
                    status="active",
                    purchased_at=row.purchased_at or paid_at,
                    expires_at=cycle.period_end,
                    auto_renew=auto_renew,
                    environment=settings.mollie_billing_environment,
                    verification_data=data,
                ),
            )
        elif status in FAILED_PAYMENT_STATUSES or status == "cancelled":
            cycle.status = "failed" if status != "cancelled" else "cancelled"
            if cycle.operation == "renewal":
                paid_through = cycle.period_start
                grace_until = _grace_expiry(data, paid_through)
                row.status = "grace_period" if grace_until > datetime.now(UTC) else "expired"
                row.expires_at = grace_until
                row.auto_renew = bool(row.auto_renew)
                row.verification_data_encrypted = encrypt_config(data)
            else:
                row.status = "pending"
                row.verification_data_encrypted = encrypt_config(data)
        else:
            cycle.status = "payment_pending"
            if cycle.operation == "renewal" and cycle.period_start <= datetime.now(UTC):
                grace_until = _grace_expiry(data, cycle.period_start)
                row.status = "grace_period" if grace_until > datetime.now(UTC) else "expired"
                row.expires_at = grace_until
            else:
                row.status = "pending"
            row.verification_data_encrypted = encrypt_config(data)
        await session.flush()

    if invoice_id is not None:
        try:
            await _ensure_receipt(invoice_id)
        except MollieBillingUnavailable:
            logger.exception("Mollie receipt creation deferred", extra={"invoice_id": str(invoice_id)})
    return organization_id


async def _process_legacy_payment_payload(payment: dict[str, Any]) -> UUID:
    organization_id = _verified_metadata(payment)
    payment_id = payment.get("id")
    if not isinstance(payment_id, str):
        raise MollieBillingVerificationError("Mollie payment reference is missing")
    async with SessionLocal.begin() as session:
        row = await _mollie_row(session, organization_id, lock=True)
        if row is None:
            raise MollieBillingVerificationError("Legacy Mollie payment is not linked")
        data = _verification_data(row)
        amount, currency = _stored_billing_terms(data)
        if not _payment_amount_matches(payment, amount, currency):
            raise MollieBillingVerificationError("Legacy Mollie payment amount is invalid")
        sequence_type = str(payment.get("sequenceType", ""))
        status = _remote_payment_status(payment.get("status"))
        data.update({"last_payment_id": payment_id, "last_payment_status": status})
        if sequence_type == "first" and data.get("initial_payment_id") == payment_id and status == "paid":
            customer_id = payment.get("customerId")
            if not isinstance(customer_id, str):
                raise MollieBillingVerificationError("Legacy Mollie customer is missing")
            mandate_id = await _valid_mandate(customer_id)
            paid_at = _parse_datetime(payment.get("paidAt")) or datetime.now(UTC)
            period_end = _add_year_datetime(paid_at)
            data.update({"mandate_id": mandate_id, "paid_through": period_end.isoformat()})
            recipient = json.dumps(_invoice_recipient(await _load_profile(session, organization_id)), ensure_ascii=False)
            decision = await _prepare_profile_tax(await _load_profile(session, organization_id))
            cycle = BillingCycle(
                id=uuid4(), organization_id=organization_id, subscription_id=row.id,
                billing_key=f"ZM:{uuid4()}", operation="initial", status="paid",
                provider=MOLLIE_PROVIDER, provider_environment=settings.mollie_billing_environment,
                product_id=PRO_PRODUCT_ID, tariff_version=str(data.get("billing_tariff_version") or PRO_YEARLY_TARIFF.version),
                period_start=paid_at, period_end=period_end, gross_amount=Decimal(amount), currency=currency,
                tax_rate=decision.rate, tax_scheme=decision.vat_scheme, tax_treatment=decision.treatment,
                tax_rule_version=decision.rule_version, recipient_json=recipient,
            )
            session.add(cycle)
            await session.flush()
            tx = BillingPaymentTransaction(
                cycle_id=cycle.id, organization_id=organization_id, provider=MOLLIE_PROVIDER,
                provider_environment=settings.mollie_billing_environment, attempt=1, status="paid",
                sequence_type="first", provider_reference=payment_id, gross_amount=Decimal(amount),
                currency=currency, paid_at=paid_at, last_synced_at=datetime.now(UTC),
            )
            session.add(tx)
            await session.flush()
            invoice = await _invoice_record(session, cycle, tx, source_payment_id=payment_id)
            await apply_verified_subscription(
                session, organization_id,
                VerifiedSubscription(
                    provider=MOLLIE_PROVIDER, product_id=PRO_PRODUCT_ID, external_reference=mandate_id,
                    account_token=str(organization_id), status="active", purchased_at=paid_at,
                    expires_at=period_end, auto_renew=True, environment=settings.mollie_billing_environment,
                    verification_data={**data, "billing_flow_version": 2},
                ),
            )
            invoice_id = invoice.id
        elif sequence_type == "recurring" and isinstance(data.get("subscription_id"), str):
            await _process_legacy_subscription_payment(session, row, data, payment)
            invoice_id = None
        else:
            row.verification_data_encrypted = encrypt_config(data)
            row.last_verified_at = datetime.now(UTC)
            invoice_id = None
    if invoice_id is not None:
        await _ensure_receipt(invoice_id)
    return organization_id


async def _process_legacy_subscription_payment(
    session: AsyncSession,
    row: StoreSubscription,
    data: dict[str, Any],
    payment: dict[str, Any],
) -> None:
    subscription_id = data.get("subscription_id")
    customer_id = data.get("mollie_customer_id")
    if not isinstance(subscription_id, str) or not isinstance(customer_id, str):
        raise MollieBillingVerificationError("Legacy Mollie subscription binding is incomplete")
    if payment.get("subscriptionId") != subscription_id:
        raise MollieBillingVerificationError("Legacy Mollie subscription binding is invalid")
    subscription = await _request_json("GET", f"customers/{customer_id}/subscriptions/{subscription_id}")
    remote_status = str(subscription.get("status", ""))
    status = _remote_payment_status(payment.get("status"))
    data.update({"last_payment_id": payment.get("id"), "last_payment_status": status, "subscription_status": remote_status})
    if status == "paid":
        paid_at = _parse_datetime(payment.get("paidAt")) or datetime.now(UTC)
        next_payment = _parse_date(subscription.get("nextPaymentDate")) or _add_year(paid_at.date())
        expires_at = datetime.combine(next_payment, paid_at.timetz())
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        data["paid_through"] = expires_at.isoformat()
        data.pop("grace_until", None)
        await apply_verified_subscription(
            session, row.organization_id,
            VerifiedSubscription(
                provider=MOLLIE_PROVIDER, product_id=PRO_PRODUCT_ID, external_reference=subscription_id,
                account_token=str(row.organization_id), status="active" if remote_status == "active" else "on_hold",
                purchased_at=row.purchased_at or paid_at, expires_at=expires_at,
                auto_renew=remote_status == "active", environment=settings.mollie_billing_environment,
                verification_data=data,
            ),
        )
    elif status in FAILED_PAYMENT_STATUSES:
        grace_until = _grace_expiry(data, row.expires_at)
        row.expires_at = grace_until
        row.status = "grace_period" if grace_until > datetime.now(UTC) else "expired"
        row.auto_renew = remote_status in {"active", "pending"}
        row.verification_data_encrypted = encrypt_config(data)


async def _reserve_initial_checkout(organization_id: UUID) -> tuple[UUID, UUID, str, str, str, dict[str, str], str]:
    async with SessionLocal.begin() as session:
        profile = await _load_profile(session, organization_id)
        decision = await _prepare_profile_tax(profile)
        recipient = _invoice_recipient(profile)
        organization = await session.get(Organization, organization_id)
        if organization is None:
            raise MollieBillingProfileRequired("Zahlmeister account does not exist")
        context = await purchase_context(session, organization_id, MOLLIE_PROVIDER)
        if not context["purchase_allowed"]:
            raise MollieBillingConflict("A Pro subscription is already active")
        row = await _mollie_row(session, organization_id, lock=True)
        data = _verification_data(row) if row else {}
        customer_id = data.get("mollie_customer_id")
        locale = organization.locale

    if not isinstance(customer_id, str):
        async with SessionLocal() as session:
            profile = await _load_profile(session, organization_id)
            organization = await session.get(Organization, organization_id)
            row = await _mollie_row(session, organization_id)
            data = _verification_data(row) if row else {}
            customer_id = await _ensure_customer(organization_id, profile, organization.locale if organization else "en", data)

    async with SessionLocal.begin() as session:
        profile = await _load_profile(session, organization_id)
        decision = await _prepare_profile_tax(profile)
        recipient = _invoice_recipient(profile)
        row = await _mollie_row(session, organization_id, lock=True)
        if row is None:
            row = StoreSubscription(organization_id=organization_id, provider=MOLLIE_PROVIDER, product_id=PRO_PRODUCT_ID)
            session.add(row)
            await session.flush()
        data = _verification_data(row)
        data["mollie_customer_id"] = customer_id

        open_cycle = await session.scalar(
            select(BillingCycle)
            .where(
                BillingCycle.organization_id == organization_id,
                BillingCycle.operation == "initial",
                BillingCycle.status.in_(["prepared", "payment_pending"]),
            )
            .order_by(BillingCycle.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if open_cycle is not None:
            tx = await session.scalar(
                select(BillingPaymentTransaction)
                .where(BillingPaymentTransaction.cycle_id == open_cycle.id)
                .order_by(BillingPaymentTransaction.attempt.desc())
                .limit(1)
                .with_for_update()
            )
            if tx is not None:
                return open_cycle.id, tx.id, customer_id, locale, _customer_name(profile), _billing_address(profile), profile.country

        now = datetime.now(UTC)
        cycle_id = uuid4()
        cycle = BillingCycle(
            id=cycle_id,
            organization_id=organization_id,
            subscription_id=row.id,
            billing_key=f"ZM:{cycle_id}",
            operation="initial",
            status="prepared",
            provider=MOLLIE_PROVIDER,
            provider_environment=settings.mollie_billing_environment,
            product_id=PRO_PRODUCT_ID,
            tariff_version=PRO_YEARLY_TARIFF.version,
            period_start=now,
            period_end=_add_year_datetime(now),
            gross_amount=Decimal(amount_value()),
            currency=settings.mollie_billing_currency.strip().upper(),
            tax_rate=decision.rate,
            tax_scheme=decision.vat_scheme,
            tax_treatment=decision.treatment,
            tax_rule_version=decision.rule_version,
            recipient_json=json.dumps(recipient, ensure_ascii=False, separators=(",", ":")),
        )
        session.add(cycle)
        await session.flush()
        tx = BillingPaymentTransaction(
            cycle_id=cycle.id,
            organization_id=organization_id,
            provider=MOLLIE_PROVIDER,
            provider_environment=settings.mollie_billing_environment,
            attempt=1,
            status="reserved",
            sequence_type="first",
            gross_amount=cycle.gross_amount,
            currency=cycle.currency,
        )
        session.add(tx)
        await session.flush()
        data.update({
            "mollie_customer_id": customer_id,
            "billing_amount": _decimal_amount(cycle.gross_amount),
            "billing_currency": cycle.currency,
            "billing_tariff_version": cycle.tariff_version,
            "billing_recipient": recipient,
            **_tax_snapshot(decision),
            "billing_flow_version": 2,
        })
        row.status = "pending"
        row.external_reference = None
        row.environment = settings.mollie_billing_environment
        row.auto_renew = False
        row.purchased_at = None
        row.expires_at = None
        row.cancelled_at = None
        row.verification_data_encrypted = encrypt_config(data)
        row.last_verified_at = datetime.now(UTC)
        return cycle.id, tx.id, customer_id, locale, _customer_name(profile), _billing_address(profile), profile.country


async def start_checkout(
    _session: AsyncSession,
    organization_id: UUID,
    *,
    customer_name: str | None = None,
    customer_email: str | None = None,
) -> MollieCheckout:
    _require_configured()
    cycle_id, tx_id, customer_id, locale, _, billing_address, country = await _reserve_initial_checkout(organization_id)
    async with SessionLocal() as session:
        cycle = await session.get(BillingCycle, cycle_id)
        tx = await session.get(BillingPaymentTransaction, tx_id)
        if cycle is None or tx is None:
            raise MollieBillingUnavailable("Billing reservation disappeared")
        provider_reference = tx.provider_reference
        if provider_reference:
            payment = await _get_payment(provider_reference)
        else:
            payment = await _find_remote_payment(tx, cycle, customer_id)
            if payment is None:
                payload: dict[str, Any] = {
                    "amount": {"currency": tx.currency, "value": _decimal_amount(tx.gross_amount)},
                    "description": "Zahlmeister Pro",
                    "sequenceType": "first",
                    "customerId": customer_id,
                    "redirectUrl": _return_url("return"),
                    "cancelUrl": _return_url("cancelled"),
                    "billingAddress": billing_address,
                    "restrictPaymentMethodsToCountry": country,
                    "metadata": _payment_metadata(organization_id, cycle, tx),
                }
                mollie_locale = _mollie_locale(locale)
                if mollie_locale:
                    payload["locale"] = mollie_locale
                webhook = _webhook_url()
                if webhook:
                    payload["webhookUrl"] = webhook
                payment = await _request_json(
                    "POST",
                    "payments",
                    json_body=payload,
                    idempotency_key=f"zahlmeister-payment-{tx.idempotency_key}",
                )

    payment_id = payment.get("id")
    if not isinstance(payment_id, str) or not payment_id.startswith("tr_"):
        raise MollieBillingUnavailable("Mollie checkout creation failed")
    checkout = _checkout_url(payment)
    status = _remote_payment_status(payment.get("status"))
    async with SessionLocal.begin() as session:
        row = await _mollie_row(session, organization_id, lock=True)
        cycle = await session.get(BillingCycle, cycle_id, with_for_update=True)
        tx = await session.get(BillingPaymentTransaction, tx_id, with_for_update=True)
        if row is None or cycle is None or tx is None:
            raise MollieBillingUnavailable("Billing reservation disappeared")
        if tx.provider_reference and tx.provider_reference != payment_id:
            raise MollieBillingVerificationError("Mollie payment binding changed unexpectedly")
        tx.provider_reference = payment_id
        tx.status = status if status in {"open", "pending", "paid", "failed", "cancelled", "expired"} else "pending"
        tx.last_synced_at = datetime.now(UTC)
        cycle.status = "payment_pending" if status in OPEN_PAYMENT_STATUSES else cycle.status
        data = _verification_data(row)
        data.update({"initial_payment_id": payment_id, "checkout_url": checkout, "last_payment_id": payment_id, "last_payment_status": status})
        row.external_reference = payment_id
        row.verification_data_encrypted = encrypt_config(data)
        row.last_verified_at = datetime.now(UTC)

    if status == "paid":
        await _process_payment_payload(await _get_payment(payment_id))
        raise MollieBillingConflict("The Pro subscription is already active")
    if not checkout:
        raise MollieBillingUnavailable("Mollie checkout URL is unavailable")
    return MollieCheckout(checkout, payment_id, provider_reference is not None)


async def process_payment(_session: AsyncSession, payment_id: str) -> UUID:
    if not payment_id.startswith("tr_"):
        raise MollieBillingVerificationError("Invalid Mollie payment reference")
    return await _process_payment_payload(await _get_payment(payment_id))


async def _reserve_due_renewal(organization_id: UUID) -> tuple[UUID, UUID, str, str] | None:
    async with SessionLocal.begin() as session:
        row = await _mollie_row(session, organization_id, lock=True)
        if row is None or not row.auto_renew or row.status not in {"active", "grace_period", "expired"}:
            return None
        data = _verification_data(row)
        if isinstance(data.get("subscription_id"), str):
            return None
        paid_through = _parse_datetime(data.get("paid_through")) or row.expires_at
        if paid_through is None or paid_through > datetime.now(UTC):
            return None
        customer_id = data.get("mollie_customer_id")
        mandate_id = data.get("mandate_id")
        if not isinstance(customer_id, str) or not isinstance(mandate_id, str):
            raise MollieBillingVerificationError("Stored Mollie mandate binding is incomplete")
        profile = await _load_profile(session, organization_id)
        decision = await _prepare_profile_tax(profile)
        recipient = _invoice_recipient(profile)
        amount, currency = _stored_billing_terms(data)
        period_start = _normalize_utc(paid_through)
        period_end = _add_year_datetime(period_start)
        cycle = await session.scalar(
            select(BillingCycle).where(
                BillingCycle.organization_id == organization_id,
                BillingCycle.provider == MOLLIE_PROVIDER,
                BillingCycle.product_id == PRO_PRODUCT_ID,
                BillingCycle.period_start == period_start,
            ).with_for_update()
        )
        if cycle is None:
            cycle_id = uuid4()
            cycle = BillingCycle(
                id=cycle_id, organization_id=organization_id, subscription_id=row.id,
                billing_key=f"ZM:{cycle_id}", operation="renewal", status="prepared",
                provider=MOLLIE_PROVIDER, provider_environment=settings.mollie_billing_environment,
                product_id=PRO_PRODUCT_ID, tariff_version=str(data.get("billing_tariff_version") or PRO_YEARLY_TARIFF.version),
                period_start=period_start, period_end=period_end, gross_amount=Decimal(amount), currency=currency,
                tax_rate=decision.rate, tax_scheme=decision.vat_scheme, tax_treatment=decision.treatment,
                tax_rule_version=decision.rule_version,
                recipient_json=json.dumps(recipient, ensure_ascii=False, separators=(",", ":")),
            )
            session.add(cycle)
            await session.flush()
        if cycle.status == "paid":
            return None
        open_tx = await session.scalar(
            select(BillingPaymentTransaction)
            .where(
                BillingPaymentTransaction.cycle_id == cycle.id,
                BillingPaymentTransaction.status.in_(["reserved", "open", "pending"]),
            )
            .order_by(BillingPaymentTransaction.attempt.desc())
            .limit(1)
            .with_for_update()
        )
        if open_tx is not None:
            return cycle.id, open_tx.id, customer_id, mandate_id
        max_attempt = await session.scalar(
            select(func.max(BillingPaymentTransaction.attempt)).where(BillingPaymentTransaction.cycle_id == cycle.id)
        ) or 0
        if max_attempt >= MAX_RENEWAL_RETRIES:
            grace_until = _grace_expiry(data, period_start)
            row.status = "grace_period" if grace_until > datetime.now(UTC) else "expired"
            row.expires_at = grace_until
            row.verification_data_encrypted = encrypt_config(data)
            return None
        tx = BillingPaymentTransaction(
            cycle_id=cycle.id, organization_id=organization_id, provider=MOLLIE_PROVIDER,
            provider_environment=settings.mollie_billing_environment, attempt=max_attempt + 1,
            status="reserved", sequence_type="recurring", gross_amount=cycle.gross_amount, currency=cycle.currency,
        )
        session.add(tx)
        cycle.retry_count = max_attempt
        cycle.status = "prepared"
        await session.flush()
        return cycle.id, tx.id, customer_id, mandate_id


async def _execute_due_renewal(organization_id: UUID) -> bool:
    reserved = await _reserve_due_renewal(organization_id)
    if reserved is None:
        return False
    cycle_id, tx_id, customer_id, mandate_id = reserved
    await _valid_mandate(customer_id, mandate_id)
    async with SessionLocal() as session:
        cycle = await session.get(BillingCycle, cycle_id)
        tx = await session.get(BillingPaymentTransaction, tx_id)
        if cycle is None or tx is None:
            raise MollieBillingUnavailable("Billing reservation disappeared")
        if tx.provider_reference:
            payment = await _get_payment(tx.provider_reference)
        else:
            payment = await _find_remote_payment(tx, cycle, customer_id)
            if payment is None:
                webhook = _webhook_url()
                payload: dict[str, Any] = {
                    "amount": {"currency": tx.currency, "value": _decimal_amount(tx.gross_amount)},
                    "description": "Zahlmeister Pro renewal",
                    "sequenceType": "recurring",
                    "customerId": customer_id,
                    "mandateId": mandate_id,
                    "metadata": _payment_metadata(organization_id, cycle, tx),
                }
                if webhook:
                    payload["webhookUrl"] = webhook
                payment = await _request_json(
                    "POST", "payments", json_body=payload,
                    idempotency_key=f"zahlmeister-payment-{tx.idempotency_key}",
                )
    payment_id = payment.get("id")
    if not isinstance(payment_id, str) or not payment_id.startswith("tr_"):
        raise MollieBillingUnavailable("Mollie renewal payment creation failed")
    async with SessionLocal.begin() as session:
        row = await _mollie_row(session, organization_id, lock=True)
        cycle = await session.get(BillingCycle, cycle_id, with_for_update=True)
        tx = await session.get(BillingPaymentTransaction, tx_id, with_for_update=True)
        if row is None or cycle is None or tx is None:
            raise MollieBillingUnavailable("Billing reservation disappeared")
        if not row.auto_renew and tx.provider_reference is None:
            cycle.status = "cancelled"
            tx.status = "cancelled"
            return False
        tx.provider_reference = payment_id
        tx.status = _remote_payment_status(payment.get("status"))
        tx.last_synced_at = datetime.now(UTC)
        cycle.status = "payment_pending"
    await _process_payment_payload(await _get_payment(payment_id))
    return True


async def _sync_receipts(organization_id: UUID | None = None) -> int:
    async with SessionLocal() as session:
        statement = select(BillingInvoice.id).where(
            BillingInvoice.provider == MOLLIE_PROVIDER,
            BillingInvoice.status.in_(OPEN_INVOICE_STATUSES),
        )
        if organization_id is not None:
            statement = statement.where(BillingInvoice.organization_id == organization_id)
        ids = (await session.execute(statement.order_by(BillingInvoice.created_at).limit(100))).scalars().all()
    processed = 0
    for invoice_id in ids:
        async with SessionLocal() as session:
            item = await session.get(BillingInvoice, invoice_id)
            if item is None:
                continue
            details = _invoice_details(item)
            if item.external_id:
                payload = await _get_sales_invoice(item.external_id)
                async with SessionLocal.begin() as update_session:
                    locked = await update_session.get(BillingInvoice, invoice_id, with_for_update=True)
                    if locked is not None:
                        await _apply_invoice_payload(update_session, locked, payload)
                processed += 1
                continue
            remote = await _find_remote_invoice(item)
            if remote is not None:
                async with SessionLocal.begin() as update_session:
                    locked = await update_session.get(BillingInvoice, invoice_id, with_for_update=True)
                    if locked is not None:
                        await _apply_invoice_payload(update_session, locked, remote)
                processed += 1
                continue
            if details.get("kind") in {"initial_receipt", "renewal_receipt"}:
                await _ensure_receipt(invoice_id)
                processed += 1
            elif details.get("kind") == "renewal":
                # Pre-v2 unbound renewal invoices could have been charge-producing.
                # Never re-issue them blindly after the architecture upgrade.
                raise MollieBillingConflict("Legacy renewal invoice requires reconciliation")
    return processed


async def _reconcile_legacy_subscription(organization_id: UUID, customer_id: str, subscription_id: str) -> None:
    subscription = await _request_json("GET", f"customers/{customer_id}/subscriptions/{subscription_id}")
    payments_payload = await _request_json(
        "GET", f"customers/{customer_id}/subscriptions/{subscription_id}/payments",
        params={"limit": 10, "sort": "desc"},
    )
    payments = _embedded_rows(payments_payload, ("payments",))
    if payments:
        await _process_legacy_payment_payload(payments[0])
        return
    async with SessionLocal.begin() as session:
        row = await _mollie_row(session, organization_id, lock=True)
        if row is None:
            return
        remote_status = str(subscription.get("status", ""))
        row.status = {"active": "active", "pending": "pending", "canceled": "cancelled", "completed": "expired", "suspended": "on_hold"}.get(remote_status, "on_hold")
        row.auto_renew = remote_status == "active"
        data = _verification_data(row)
        data["subscription_status"] = remote_status
        row.verification_data_encrypted = encrypt_config(data)
        row.last_verified_at = datetime.now(UTC)


async def sync_subscription(_session: AsyncSession, organization_id: UUID) -> None:
    _require_configured()
    async with SessionLocal() as session:
        row = await _mollie_row(session, organization_id)
        if row is None:
            return
        data = _verification_data(row)
        legacy_customer = data.get("mollie_customer_id")
        legacy_subscription = data.get("subscription_id")
        tx_ids = (
            await session.execute(
                select(BillingPaymentTransaction.id)
                .where(
                    BillingPaymentTransaction.organization_id == organization_id,
                    BillingPaymentTransaction.provider == MOLLIE_PROVIDER,
                    BillingPaymentTransaction.status.in_(["reserved", "open", "pending"]),
                )
                .order_by(BillingPaymentTransaction.created_at)
            )
        ).scalars().all()
    if isinstance(legacy_customer, str) and isinstance(legacy_subscription, str):
        await _reconcile_legacy_subscription(organization_id, legacy_customer, legacy_subscription)
        return
    for tx_id in tx_ids:
        async with SessionLocal() as session:
            tx = await session.get(BillingPaymentTransaction, tx_id)
            if tx is None:
                continue
            cycle = await session.get(BillingCycle, tx.cycle_id)
            row = await _mollie_row(session, organization_id)
            if cycle is None or row is None:
                continue
            data = _verification_data(row)
            customer_id = data.get("mollie_customer_id")
            if not isinstance(customer_id, str):
                continue
            if tx.provider_reference:
                payment = await _get_payment(tx.provider_reference)
            else:
                payment = await _find_remote_payment(tx, cycle, customer_id)
            if payment is not None:
                await _process_payment_payload(payment)
    await _sync_receipts(organization_id)
    await _execute_due_renewal(organization_id)


async def run_billing_cycle(_session: AsyncSession) -> dict[str, int]:
    if not billing_configured():
        return {"invoices_synced": 0, "renewals_created": 0}
    invoices_synced = await _sync_receipts()
    async with SessionLocal() as session:
        ids = (
            await session.execute(
                select(StoreSubscription.organization_id).where(
                    StoreSubscription.provider == MOLLIE_PROVIDER,
                    StoreSubscription.auto_renew.is_(True),
                    StoreSubscription.status.in_(["active", "grace_period", "expired"]),
                ).order_by(StoreSubscription.expires_at).limit(100)
            )
        ).scalars().all()
    renewals = 0
    for organization_id in ids:
        if await _execute_due_renewal(organization_id):
            renewals += 1
    return {"invoices_synced": invoices_synced, "renewals_created": renewals}


async def cancel_subscription(_session: AsyncSession, organization_id: UUID) -> None:
    _require_configured()
    legacy_customer: str | None = None
    legacy_subscription: str | None = None
    async with SessionLocal.begin() as session:
        row = await _mollie_row(session, organization_id, lock=True)
        if row is None:
            raise MollieBillingConflict("No Mollie subscription exists")
        data = _verification_data(row)
        if isinstance(data.get("mollie_customer_id"), str) and isinstance(data.get("subscription_id"), str):
            legacy_customer = data["mollie_customer_id"]
            legacy_subscription = data["subscription_id"]
        now = datetime.now(UTC)
        paid_through = _parse_datetime(data.get("paid_through")) or row.expires_at
        row.auto_renew = False
        row.cancelled_at = now
        row.expires_at = paid_through
        row.status = "cancelled" if paid_through and paid_through > now else "expired"
        row.last_verified_at = now
        data.pop("grace_until", None)
        row.verification_data_encrypted = encrypt_config(data)

        cycles = (
            await session.execute(
                select(BillingCycle).where(
                    BillingCycle.organization_id == organization_id,
                    BillingCycle.operation == "renewal",
                    BillingCycle.status.in_(["prepared", "payment_pending"]),
                ).with_for_update()
            )
        ).scalars().all()
        for cycle in cycles:
            tx = await session.scalar(
                select(BillingPaymentTransaction)
                .where(BillingPaymentTransaction.cycle_id == cycle.id)
                .order_by(BillingPaymentTransaction.attempt.desc())
                .limit(1)
                .with_for_update()
            )
            if tx is not None and tx.provider_reference is None:
                tx.status = "cancelled"
                cycle.status = "cancelled"

    if legacy_customer and legacy_subscription:
        await _request_json("DELETE", f"customers/{legacy_customer}/subscriptions/{legacy_subscription}")
        async with SessionLocal.begin() as session:
            row = await _mollie_row(session, organization_id, lock=True)
            if row is not None:
                data = _verification_data(row)
                data.pop("subscription_id", None)
                data.pop("subscription_status", None)
                row.verification_data_encrypted = encrypt_config(data)
