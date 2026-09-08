from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.billing_catalog import PRO_YEARLY_TARIFF
from app.core.config import settings
from app.models.billing import BillingInvoice, BillingProfile
from app.models.entities import Organization
from app.models.platform import StoreSubscription
from app.services.billing import (
    PRO_PRODUCT_ID,
    VerifiedSubscription,
    apply_verified_subscription,
    purchase_context,
)
from app.services.billing_tax import TaxDecision, tax_decision
from app.services.secrets import decrypt_config, encrypt_config

logger = logging.getLogger(__name__)

MOLLIE_PROVIDER = "mollie"
MOLLIE_INTERVAL = PRO_YEARLY_TARIFF.interval
MOLLIE_PURPOSE = "zahlmeister_pro_subscription"
MOLLIE_GRACE_DAYS = 7
OPEN_PAYMENT_STATUSES = {"open", "pending"}
FAILED_PAYMENT_STATUSES = {"failed", "canceled", "expired"}
USABLE_MANDATE_STATUSES = {"valid"}
OPEN_INVOICE_STATUSES = {"creating", "pending-payment", "issued", "overdue", "payment-reversed"}


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


def _require_configured() -> None:
    if not billing_configured():
        raise MollieBillingUnavailable("Mollie billing is not configured")


def _decimal_amount(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _vat_rate_value(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


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
    base = settings.public_app_url.rstrip("/")
    return f"{base}/app?view=billing&billing={result}"


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
        actual = Decimal(str(amount.get("value", "")))
        expected = Decimal(wanted_amount)
    except InvalidOperation:
        return False
    return actual == expected


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
    base = paid_through or current
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    else:
        base = base.astimezone(UTC)
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


async def _get_subscription(customer_id: str, subscription_id: str) -> dict[str, Any]:
    return await _request_json("GET", f"customers/{customer_id}/subscriptions/{subscription_id}")


async def _latest_subscription_payments(
    customer_id: str,
    subscription_id: str,
) -> list[dict[str, Any]]:
    payload = await _request_json(
        "GET",
        f"customers/{customer_id}/subscriptions/{subscription_id}/payments",
        params={"limit": 10, "sort": "desc"},
    )
    embedded = payload.get("_embedded")
    if not isinstance(embedded, dict):
        return []
    payments = embedded.get("payments")
    return [item for item in payments if isinstance(item, dict)] if isinstance(payments, list) else []


def _checkout_url(payment: dict[str, Any]) -> str | None:
    links = payment.get("_links")
    checkout = links.get("checkout") if isinstance(links, dict) else None
    href = checkout.get("href") if isinstance(checkout, dict) else None
    return href if isinstance(href, str) and href.startswith("https://") else None


def _invoice_payment_url(payload: dict[str, Any]) -> str | None:
    links = payload.get("_links")
    payment = links.get("invoicePayment") if isinstance(links, dict) else None
    href = payment.get("href") if isinstance(payment, dict) else None
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
    fallback = {
        "de": "de_AT", "en": "en_GB", "fr": "fr_FR", "es": "es_ES", "it": "it_IT",
        "nl": "nl_NL", "pt": "pt_PT", "pl": "pl_PL", "cs": "cs_CZ", "da": "da_DK",
        "fi": "fi_FI", "hu": "hu_HU", "lt": "lt_LT", "lv": "lv_LV", "sk": "sk_SK",
        "sv": "sv_SE",
    }
    return fallback.get(language)


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
            raise MollieBillingProfileRequired(
                "Business billing requires a VAT number or organization number"
            )
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
    profile.vat_validation_status = decision.vat_validation_status
    profile.vat_validated_at = decision.vat_validated_at
    return decision


async def _ensure_customer(
    organization_id: UUID,
    profile: BillingProfile,
    organization_locale: str,
    data: dict[str, Any],
) -> str:
    payload: dict[str, Any] = {
        "name": _customer_name(profile)[:255],
        "email": profile.billing_email,
    }
    locale = _mollie_locale(organization_locale)
    if locale:
        payload["locale"] = locale
    existing = data.get("mollie_customer_id")
    if isinstance(existing, str) and existing.startswith("cst_"):
        await _request_json("PATCH", f"customers/{existing}", json_body=payload)
        return existing
    payload["metadata"] = {
        "purpose": "zahlmeister_billing_customer",
        "organization_id": str(organization_id),
    }
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
        "subscription_id",
        "mandate_id",
        "subscription_status",
        "initial_payment_id",
        "checkout_url",
        "checkout_attempt",
        "last_payment_id",
        "last_payment_status",
        "billing_amount",
        "billing_currency",
        "billing_tariff_version",
        "billing_recipient",
        "billing_tax_rate",
        "billing_vat_scheme",
        "billing_tax_treatment",
        "billing_tax_rule_version",
        "latest_invoice_id",
        "paid_through",
        "grace_until",
    ):
        data.pop(key, None)


def _stored_recipient(data: dict[str, Any]) -> dict[str, str] | None:
    value = data.get("billing_recipient")
    if not isinstance(value, dict):
        return None
    recipient = {str(key): str(item) for key, item in value.items() if item is not None}
    return recipient if recipient.get("type") in {"business", "consumer"} else None


def _stored_tax(data: dict[str, Any]) -> tuple[Decimal, str, str, str] | None:
    try:
        rate = Decimal(str(data["billing_tax_rate"]))
        scheme = str(data["billing_vat_scheme"])
        treatment = str(data["billing_tax_treatment"])
        version = str(data["billing_tax_rule_version"])
    except (KeyError, InvalidOperation):
        return None
    return rate, scheme, treatment, version


def _invoice_email(locale: str) -> tuple[str, str]:
    if locale.lower().startswith("de"):
        return (
            "Ihre Zahlmeister Pro Rechnung",
            "Vielen Dank. Im Anhang finden Sie Ihre Zahlmeister Pro Rechnung.",
        )
    return (
        "Your Zahlmeister Pro invoice",
        "Thank you. Your Zahlmeister Pro invoice is attached.",
    )


def _invoice_memo(treatment: str) -> str | None:
    if treatment == "eu_reverse_charge":
        return "Reverse charge - tax liability transfers to the recipient."
    return None


async def _invoice_record(
    session: AsyncSession,
    organization_id: UUID,
    *,
    period_start: datetime,
    period_end: datetime,
    amount: str,
    currency: str,
    tariff_version: str,
    recipient: dict[str, str],
    vat_rate: Decimal,
    vat_scheme: str,
    treatment: str,
    tax_rule_version: str,
    kind: str,
    source_payment_id: str | None = None,
) -> BillingInvoice:
    existing = await session.scalar(
        select(BillingInvoice)
        .where(
            BillingInvoice.organization_id == organization_id,
            BillingInvoice.provider == MOLLIE_PROVIDER,
            BillingInvoice.product_id == PRO_PRODUCT_ID,
            BillingInvoice.period_start == period_start,
        )
        .with_for_update()
    )
    if existing is not None:
        return existing
    details = {
        "kind": kind,
        "tax_rule_version": tax_rule_version,
        "recipient": recipient,
    }
    if source_payment_id:
        details["source_payment_id"] = source_payment_id
    item = BillingInvoice(
        organization_id=organization_id,
        provider=MOLLIE_PROVIDER,
        product_id=PRO_PRODUCT_ID,
        tariff_version=tariff_version,
        period_start=period_start,
        period_end=period_end,
        gross_amount=Decimal(amount),
        currency=currency,
        vat_rate=vat_rate,
        vat_scheme=vat_scheme,
        tax_treatment=treatment,
        recipient_country=recipient["country"],
        recipient_type=recipient["type"],
        recipient_vat_number=recipient.get("vatNumber"),
        status="creating",
        details_json=json.dumps(details, ensure_ascii=False, separators=(",", ":")),
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


async def _create_remote_invoice(
    item: BillingInvoice,
    *,
    customer_id: str | None,
    mandate_id: str | None,
    locale: str,
) -> dict[str, Any]:
    details = _invoice_details(item)
    recipient = details.get("recipient")
    if not isinstance(recipient, dict):
        raise MollieBillingVerificationError("Billing invoice recipient snapshot is missing")
    subject, body = _invoice_email(locale)
    payload: dict[str, Any] = {
        "status": "paid",
        "vatScheme": item.vat_scheme,
        "vatMode": "inclusive",
        "paymentTerm": "7 days",
        "recipientIdentifier": f"zahlmeister-{item.organization_id}",
        "recipient": recipient,
        "lines": [
            {
                "description": "Zahlmeister Pro - 12 months",
                "quantity": 1,
                "vatRate": _vat_rate_value(item.vat_rate),
                "unitPrice": {"currency": item.currency, "value": _decimal_amount(item.gross_amount)},
            }
        ],
        "emailDetails": {"subject": subject, "body": body},
    }
    memo = _invoice_memo(item.tax_treatment)
    if memo:
        payload["memo"] = memo
    if customer_id and mandate_id:
        payload["customerId"] = customer_id
        payload["mandateId"] = mandate_id
    else:
        payload["paymentDetails"] = {"source": "manual"}
    return await _request_json(
        "POST",
        "sales-invoices",
        json_body=payload,
        idempotency_key=f"zahlmeister-invoice-{item.idempotency_key}",
    )


async def _apply_invoice_payload(
    session: AsyncSession,
    item: BillingInvoice,
    payload: dict[str, Any],
) -> None:
    remote_id = payload.get("id")
    if not isinstance(remote_id, str) or not remote_id.startswith("invoice_"):
        raise MollieBillingVerificationError("Mollie sales invoice reference is invalid")
    if item.external_id and item.external_id != remote_id:
        raise MollieBillingVerificationError("Mollie sales invoice binding changed unexpectedly")
    recipient_identifier = payload.get("recipientIdentifier")
    if recipient_identifier not in {None, f"zahlmeister-{item.organization_id}"}:
        raise MollieBillingVerificationError("Mollie sales invoice belongs to another account")
    item.external_id = remote_id
    item.invoice_number = str(payload.get("invoiceNumber")) if payload.get("invoiceNumber") else None
    item.status = str(payload.get("status", "creating"))
    item.payment_url = _invoice_payment_url(payload)
    item.last_synced_at = datetime.now(UTC)
    if item.status == "paid":
        item.paid_at = _parse_datetime(payload.get("paidAt")) or item.paid_at or datetime.now(UTC)
    await _apply_invoice_entitlement(session, item)


async def _apply_invoice_entitlement(session: AsyncSession, item: BillingInvoice) -> None:
    row = await _mollie_row(session, item.organization_id, lock=True)
    if row is None:
        return
    data = _verification_data(row)
    details = _invoice_details(item)
    kind = str(details.get("kind", ""))
    if item.status == "paid":
        data["latest_invoice_id"] = item.external_id or str(item.id)
        data["paid_through"] = item.period_end.isoformat()
        data.pop("grace_until", None)
        reference = data.get("mandate_id") or item.external_id or str(item.id)
        await apply_verified_subscription(
            session,
            item.organization_id,
            VerifiedSubscription(
                provider=MOLLIE_PROVIDER,
                product_id=PRO_PRODUCT_ID,
                external_reference=str(reference),
                account_token=str(item.organization_id),
                status="active",
                purchased_at=row.purchased_at or item.period_start,
                expires_at=item.period_end,
                auto_renew=bool(row.auto_renew),
                environment=settings.mollie_billing_environment,
                verification_data=data,
            ),
        )
        return
    if kind != "renewal":
        return
    paid_through = item.period_start
    now = datetime.now(UTC)
    if item.status in {"issued", "overdue", "payment-reversed"}:
        grace_until = _grace_expiry(data, paid_through, now=now)
        row.expires_at = grace_until
        row.status = "grace_period" if grace_until > now else "expired"
        row.last_verified_at = now
        row.verification_data_encrypted = encrypt_config(data)
        await session.flush()
    elif item.status == "cancelled":
        row.auto_renew = False
        row.status = "cancelled" if paid_through > now else "expired"
        row.expires_at = paid_through
        row.cancelled_at = now
        row.last_verified_at = now
        row.verification_data_encrypted = encrypt_config(data)
        await session.flush()


async def _sync_invoice_item(session: AsyncSession, item: BillingInvoice) -> None:
    if not item.external_id:
        return
    payload = await _get_sales_invoice(item.external_id)
    await _apply_invoice_payload(session, item, payload)


async def _create_initial_receipt(
    session: AsyncSession,
    row: StoreSubscription,
    data: dict[str, Any],
    payment_id: str,
    paid_at: datetime,
) -> BillingInvoice:
    recipient = _stored_recipient(data)
    stored_tax = _stored_tax(data)
    if recipient is None or stored_tax is None:
        profile = await _load_profile(session, row.organization_id)
        decision = await _prepare_profile_tax(profile)
        recipient = _invoice_recipient(profile)
        stored_tax = (decision.rate, decision.vat_scheme, decision.treatment, decision.rule_version)
    rate, scheme, treatment, tax_rule_version = stored_tax
    amount, currency = _stored_billing_terms(data)
    item = await _invoice_record(
        session,
        row.organization_id,
        period_start=paid_at,
        period_end=_add_year_datetime(paid_at),
        amount=amount,
        currency=currency,
        tariff_version=str(data.get("billing_tariff_version") or PRO_YEARLY_TARIFF.version),
        recipient=recipient,
        vat_rate=rate,
        vat_scheme=scheme,
        treatment=treatment,
        tax_rule_version=tax_rule_version,
        kind="initial",
        source_payment_id=payment_id,
    )
    if not item.external_id:
        organization = await session.get(Organization, row.organization_id)
        locale = organization.locale if organization else "en"
        try:
            payload = await _create_remote_invoice(
                item,
                customer_id=None,
                mandate_id=None,
                locale=locale,
            )
            await _apply_invoice_payload(session, item, payload)
        except MollieBillingUnavailable:
            logger.exception("Initial Mollie sales invoice creation will be retried")
    return item


async def start_checkout(
    session: AsyncSession,
    organization_id: UUID,
    *,
    customer_name: str | None = None,
    customer_email: str | None = None,
) -> MollieCheckout:
    _require_configured()
    profile = await _load_profile(session, organization_id)
    decision = await _prepare_profile_tax(profile)
    recipient = _invoice_recipient(profile)
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise MollieBillingProfileRequired("Zahlmeister account does not exist")

    existing = await _mollie_row(session, organization_id, lock=True)
    if existing is not None:
        data = _verification_data(existing)
        subscription_id = data.get("subscription_id")
        customer_id = data.get("mollie_customer_id")
        if isinstance(subscription_id, str) and isinstance(customer_id, str):
            await _reconcile_legacy_subscription(session, existing, data)

    context = await purchase_context(session, organization_id, MOLLIE_PROVIDER)
    if not context["purchase_allowed"]:
        raise MollieBillingConflict("A Pro subscription is already active")

    row = await _mollie_row(session, organization_id, lock=True)
    data = _verification_data(row) if row is not None else {}
    initial_payment_id = data.get("initial_payment_id")
    if isinstance(initial_payment_id, str):
        payment = await _get_payment(initial_payment_id)
        payment_status = str(payment.get("status", ""))
        if payment_status in OPEN_PAYMENT_STATUSES:
            checkout = _checkout_url(payment)
            if checkout:
                return MollieCheckout(checkout, initial_payment_id, True)
        if payment_status == "paid":
            await _process_payment_payload(session, payment)
            context = await purchase_context(session, organization_id, MOLLIE_PROVIDER)
            if not context["purchase_allowed"]:
                raise MollieBillingConflict("The Pro subscription is already active")

    customer_id = await _ensure_customer(organization_id, profile, organization.locale, data)
    _reset_finished_subscription_data(data)
    billing_amount, billing_currency = _current_billing_terms()
    checkout_attempt = str(uuid4())
    payment_payload: dict[str, Any] = {
        "amount": {"currency": billing_currency, "value": billing_amount},
        "description": "Zahlmeister Pro",
        "sequenceType": "first",
        "redirectUrl": _return_url("return"),
        "cancelUrl": _return_url("cancelled"),
        "billingAddress": _billing_address(profile),
        "restrictPaymentMethodsToCountry": profile.country,
        "metadata": _metadata(organization_id),
    }
    locale = _mollie_locale(organization.locale)
    if locale:
        payment_payload["locale"] = locale
    webhook_url = _webhook_url()
    if webhook_url:
        payment_payload["webhookUrl"] = webhook_url
    payment = await _request_json(
        "POST",
        f"customers/{customer_id}/payments",
        json_body=payment_payload,
        idempotency_key=f"zahlmeister-first-{organization_id}-{checkout_attempt}",
    )
    payment_id = payment.get("id")
    checkout = _checkout_url(payment)
    if not isinstance(payment_id, str) or not payment_id.startswith("tr_") or not checkout:
        raise MollieBillingUnavailable("Mollie checkout creation failed")

    if row is None:
        row = StoreSubscription(
            organization_id=organization_id,
            provider=MOLLIE_PROVIDER,
            product_id=PRO_PRODUCT_ID,
        )
        session.add(row)
    data.update(
        {
            "mollie_customer_id": customer_id,
            "initial_payment_id": payment_id,
            "checkout_url": checkout,
            "checkout_attempt": checkout_attempt,
            "last_payment_id": payment_id,
            "last_payment_status": str(payment.get("status", "open")),
            "billing_amount": billing_amount,
            "billing_currency": billing_currency,
            "billing_tariff_version": PRO_YEARLY_TARIFF.version,
            "billing_recipient": recipient,
            **_tax_snapshot(decision),
        }
    )
    row.product_id = PRO_PRODUCT_ID
    row.status = "pending"
    row.external_reference = payment_id
    row.environment = settings.mollie_billing_environment
    row.auto_renew = False
    row.purchased_at = None
    row.expires_at = None
    row.cancelled_at = None
    row.verification_data_encrypted = encrypt_config(data)
    row.last_verified_at = datetime.now(UTC)
    await session.flush()
    return MollieCheckout(checkout, payment_id, False)


async def process_payment(session: AsyncSession, payment_id: str) -> UUID:
    if not payment_id.startswith("tr_"):
        raise MollieBillingVerificationError("Invalid Mollie payment reference")
    payment = await _get_payment(payment_id)
    return await _process_payment_payload(session, payment)


async def _process_payment_payload(
    session: AsyncSession,
    payment: dict[str, Any],
) -> UUID:
    organization_id = _verified_metadata(payment)
    payment_id = payment.get("id")
    if not isinstance(payment_id, str):
        raise MollieBillingVerificationError("Mollie payment reference is missing")

    row = await _mollie_row(session, organization_id, lock=True)
    if row is None:
        raise MollieBillingVerificationError("Mollie payment is not linked to a checkout")
    data = _verification_data(row)
    billing_amount, billing_currency = _stored_billing_terms(data)
    if not _payment_amount_matches(payment, billing_amount, billing_currency):
        raise MollieBillingVerificationError("Mollie payment amount does not match the product")

    sequence_type = str(payment.get("sequenceType", ""))
    if sequence_type == "first":
        if data.get("initial_payment_id") != payment_id:
            raise MollieBillingVerificationError("Mollie first payment does not match the checkout")
        await _process_first_payment(session, row, data, payment)
    elif sequence_type == "recurring" and isinstance(data.get("subscription_id"), str):
        await _process_legacy_recurring_payment(session, row, data, payment)
    else:
        raise MollieBillingVerificationError("Unexpected Mollie payment sequence")
    return organization_id


async def _process_first_payment(
    session: AsyncSession,
    row: StoreSubscription,
    data: dict[str, Any],
    payment: dict[str, Any],
) -> None:
    payment_id = str(payment["id"])
    payment_status = str(payment.get("status", ""))
    data.update({"last_payment_id": payment_id, "last_payment_status": payment_status})
    row.last_verified_at = datetime.now(UTC)
    row.verification_data_encrypted = encrypt_config(data)
    if payment_status != "paid":
        await session.flush()
        return

    customer_id = data.get("mollie_customer_id")
    remote_customer_id = payment.get("customerId")
    if not isinstance(remote_customer_id, str) or remote_customer_id != customer_id:
        raise MollieBillingVerificationError("Mollie customer does not match the checkout")

    mandates_payload = await _request_json("GET", f"customers/{remote_customer_id}/mandates")
    embedded = mandates_payload.get("_embedded")
    mandates = embedded.get("mandates") if isinstance(embedded, dict) else None
    mandate = (
        next(
            (
                item
                for item in mandates
                if isinstance(item, dict) and item.get("status") in USABLE_MANDATE_STATUSES
            ),
            None,
        )
        if isinstance(mandates, list)
        else None
    )
    mandate_id = mandate.get("id") if isinstance(mandate, dict) else None
    if not isinstance(mandate_id, str):
        raise MollieBillingUnavailable("Mollie mandate is not ready yet")

    paid_at = _parse_datetime(payment.get("paidAt")) or datetime.now(UTC)
    period_end = _add_year_datetime(paid_at)
    data.update(
        {
            "mandate_id": mandate_id,
            "last_payment_id": payment_id,
            "last_payment_status": "paid",
            "paid_through": period_end.isoformat(),
        }
    )
    data.pop("grace_until", None)
    await _create_initial_receipt(session, row, data, payment_id, paid_at)
    await apply_verified_subscription(
        session,
        row.organization_id,
        VerifiedSubscription(
            provider=MOLLIE_PROVIDER,
            product_id=PRO_PRODUCT_ID,
            external_reference=mandate_id,
            account_token=str(row.organization_id),
            status="active",
            purchased_at=paid_at,
            expires_at=period_end,
            auto_renew=True,
            environment=settings.mollie_billing_environment,
            verification_data=data,
        ),
    )


def _paid_through(row: StoreSubscription, data: dict[str, Any]) -> datetime | None:
    return _parse_datetime(data.get("paid_through")) or row.expires_at


async def _create_due_renewal(
    session: AsyncSession,
    row: StoreSubscription,
    data: dict[str, Any],
    *,
    now: datetime | None = None,
) -> BillingInvoice | None:
    if not row.auto_renew or isinstance(data.get("subscription_id"), str):
        return None
    current = now or datetime.now(UTC)
    paid_through = _paid_through(row, data)
    if paid_through is None or paid_through > current:
        return None
    profile = await _load_profile(session, row.organization_id)
    decision = await _prepare_profile_tax(profile)
    recipient = _invoice_recipient(profile)
    amount, currency = _current_billing_terms()
    period_start = paid_through
    period_end = _add_year_datetime(period_start)
    item = await _invoice_record(
        session,
        row.organization_id,
        period_start=period_start,
        period_end=period_end,
        amount=amount,
        currency=currency,
        tariff_version=PRO_YEARLY_TARIFF.version,
        recipient=recipient,
        vat_rate=decision.rate,
        vat_scheme=decision.vat_scheme,
        treatment=decision.treatment,
        tax_rule_version=decision.rule_version,
        kind="renewal",
    )
    if item.external_id:
        await _sync_invoice_item(session, item)
        return item
    customer_id = data.get("mollie_customer_id")
    mandate_id = data.get("mandate_id")
    if not isinstance(customer_id, str) or not isinstance(mandate_id, str):
        raise MollieBillingVerificationError("Stored Mollie mandate binding is incomplete")
    mandate = await _request_json("GET", f"customers/{customer_id}/mandates/{mandate_id}")
    if mandate.get("status") != "valid":
        raise MollieBillingConflict("Mollie mandate is no longer valid")
    organization = await session.get(Organization, row.organization_id)
    locale = organization.locale if organization else "en"
    payload = await _create_remote_invoice(
        item,
        customer_id=customer_id,
        mandate_id=mandate_id,
        locale=locale,
    )
    await _apply_invoice_payload(session, item, payload)
    data["latest_invoice_id"] = item.external_id or str(item.id)
    row.verification_data_encrypted = encrypt_config(data)
    await session.flush()
    return item


async def _retry_local_invoice(session: AsyncSession, item: BillingInvoice) -> None:
    details = _invoice_details(item)
    kind = details.get("kind")
    row = await _mollie_row(session, item.organization_id, lock=True)
    if row is None:
        return
    data = _verification_data(row)
    organization = await session.get(Organization, item.organization_id)
    locale = organization.locale if organization else "en"
    if kind == "initial":
        payload = await _create_remote_invoice(item, customer_id=None, mandate_id=None, locale=locale)
    elif kind == "renewal":
        customer_id = data.get("mollie_customer_id")
        mandate_id = data.get("mandate_id")
        if not isinstance(customer_id, str) or not isinstance(mandate_id, str):
            raise MollieBillingVerificationError("Stored Mollie mandate binding is incomplete")
        payload = await _create_remote_invoice(
            item,
            customer_id=customer_id,
            mandate_id=mandate_id,
            locale=locale,
        )
    else:
        raise MollieBillingVerificationError("Unknown local billing invoice kind")
    await _apply_invoice_payload(session, item, payload)


async def sync_sales_invoices(session: AsyncSession, organization_id: UUID | None = None) -> int:
    statement = select(BillingInvoice).where(
        BillingInvoice.provider == MOLLIE_PROVIDER,
        BillingInvoice.status.in_(OPEN_INVOICE_STATUSES),
    )
    if organization_id is not None:
        statement = statement.where(BillingInvoice.organization_id == organization_id)
    rows = (await session.execute(statement.order_by(BillingInvoice.created_at).limit(100))).scalars().all()
    processed = 0
    for item in rows:
        locked = await session.get(BillingInvoice, item.id, with_for_update=True)
        if locked is None:
            continue
        if locked.external_id:
            await _sync_invoice_item(session, locked)
        else:
            await _retry_local_invoice(session, locked)
        processed += 1
    return processed


async def run_billing_cycle(session: AsyncSession) -> dict[str, int]:
    if not billing_configured():
        return {"invoices_synced": 0, "renewals_created": 0}
    invoices_synced = await sync_sales_invoices(session)
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(StoreSubscription)
            .where(
                StoreSubscription.provider == MOLLIE_PROVIDER,
                StoreSubscription.auto_renew.is_(True),
                StoreSubscription.status.in_(["active", "grace_period", "expired"]),
            )
            .order_by(StoreSubscription.expires_at)
            .limit(100)
        )
    ).scalars().all()
    renewals = 0
    for detached in rows:
        row = await session.get(StoreSubscription, detached.id, with_for_update=True)
        if row is None:
            continue
        data = _verification_data(row)
        item = await _create_due_renewal(session, row, data, now=now)
        if item is not None:
            renewals += 1
    return {"invoices_synced": invoices_synced, "renewals_created": renewals}


async def sync_subscription(session: AsyncSession, organization_id: UUID) -> None:
    _require_configured()
    row = await _mollie_row(session, organization_id, lock=True)
    if row is None:
        return
    data = _verification_data(row)
    if isinstance(data.get("subscription_id"), str):
        await _reconcile_legacy_subscription(session, row, data)
        return
    payment_id = data.get("initial_payment_id")
    if row.status == "pending" and isinstance(payment_id, str):
        payment = await _get_payment(payment_id)
        await _process_payment_payload(session, payment)
    await sync_sales_invoices(session, organization_id)
    row = await _mollie_row(session, organization_id, lock=True)
    if row is not None:
        await _create_due_renewal(session, row, _verification_data(row))


async def cancel_subscription(session: AsyncSession, organization_id: UUID) -> None:
    _require_configured()
    row = await _mollie_row(session, organization_id, lock=True)
    if row is None:
        raise MollieBillingConflict("No Mollie subscription exists")
    data = _verification_data(row)
    customer_id = data.get("mollie_customer_id")
    subscription_id = data.get("subscription_id")
    if isinstance(customer_id, str) and isinstance(subscription_id, str):
        await _request_json("DELETE", f"customers/{customer_id}/subscriptions/{subscription_id}")
        data.pop("subscription_id", None)
        data.pop("subscription_status", None)
    now = datetime.now(UTC)
    row.auto_renew = False
    row.cancelled_at = now
    row.status = "cancelled" if row.expires_at and row.expires_at > now else "expired"
    row.last_verified_at = now
    row.verification_data_encrypted = encrypt_config(data)
    await session.flush()


async def _process_legacy_recurring_payment(
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
        raise MollieBillingVerificationError("Legacy Mollie recurring payment binding is invalid")
    payment_status = str(payment.get("status", ""))
    subscription = await _get_subscription(customer_id, subscription_id)
    remote_status = str(subscription.get("status", ""))
    data.update(
        {
            "last_payment_id": payment.get("id"),
            "last_payment_status": payment_status,
            "subscription_status": remote_status,
        }
    )
    if payment_status == "paid":
        paid_at = _parse_datetime(payment.get("paidAt")) or datetime.now(UTC)
        next_payment = _parse_date(subscription.get("nextPaymentDate")) or _add_year(paid_at.date())
        expires_at = datetime.combine(next_payment, paid_at.timetz())
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        data["paid_through"] = expires_at.isoformat()
        data.pop("grace_until", None)
        await apply_verified_subscription(
            session,
            row.organization_id,
            VerifiedSubscription(
                provider=MOLLIE_PROVIDER,
                product_id=PRO_PRODUCT_ID,
                external_reference=subscription_id,
                account_token=str(row.organization_id),
                status="active" if remote_status == "active" else "on_hold",
                purchased_at=row.purchased_at or paid_at,
                expires_at=expires_at,
                auto_renew=remote_status == "active",
                environment=settings.mollie_billing_environment,
                verification_data=data,
            ),
        )
        return
    if payment_status in FAILED_PAYMENT_STATUSES:
        now = datetime.now(UTC)
        grace_until = _grace_expiry(data, row.expires_at, now=now)
        row.expires_at = grace_until
        row.status = "grace_period" if grace_until > now else "expired"
        row.auto_renew = remote_status in {"active", "pending"}
        row.last_verified_at = now
        row.verification_data_encrypted = encrypt_config(data)
        await session.flush()


async def _reconcile_legacy_subscription(
    session: AsyncSession,
    row: StoreSubscription,
    data: dict[str, Any],
) -> None:
    customer_id = data.get("mollie_customer_id")
    subscription_id = data.get("subscription_id")
    if not isinstance(customer_id, str) or not isinstance(subscription_id, str):
        return
    subscription = await _get_subscription(customer_id, subscription_id)
    remote_status = str(subscription.get("status", ""))
    payments = await _latest_subscription_payments(customer_id, subscription_id)
    latest = payments[0] if payments else None
    if latest is not None:
        metadata_org = _verified_metadata(latest)
        if metadata_org != row.organization_id:
            raise MollieBillingVerificationError("Legacy Mollie subscription account binding is invalid")
        amount, currency = _stored_billing_terms(data)
        if not _payment_amount_matches(latest, amount, currency):
            raise MollieBillingVerificationError("Legacy Mollie subscription amount is invalid")
        await _process_legacy_recurring_payment(session, row, data, latest)
        return
    row.status = {
        "active": "active",
        "pending": "pending",
        "canceled": "cancelled",
        "completed": "expired",
        "suspended": "on_hold",
    }.get(remote_status, "on_hold")
    row.auto_renew = remote_status == "active"
    row.last_verified_at = datetime.now(UTC)
    data["subscription_status"] = remote_status
    row.verification_data_encrypted = encrypt_config(data)
    await session.flush()
