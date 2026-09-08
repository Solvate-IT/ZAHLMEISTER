from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.platform import StoreSubscription
from app.services.billing import (
    PRO_PRODUCT_ID,
    VerifiedSubscription,
    apply_verified_subscription,
    purchase_context,
)
from app.services.secrets import decrypt_config, encrypt_config

logger = logging.getLogger(__name__)

MOLLIE_PROVIDER = "mollie"
MOLLIE_INTERVAL = "12 months"
MOLLIE_PURPOSE = "zahlmeister_pro_subscription"
MOLLIE_GRACE_DAYS = 7
OPEN_PAYMENT_STATUSES = {"open", "pending"}
FAILED_PAYMENT_STATUSES = {"failed", "canceled", "expired"}
USABLE_MANDATE_STATUSES = {"pending", "valid"}


class MollieBillingError(RuntimeError):
    pass


class MollieBillingUnavailable(MollieBillingError):
    pass


class MollieBillingConflict(MollieBillingError):
    pass


class MollieBillingVerificationError(MollieBillingError):
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
        raise MollieBillingUnavailable("Mollie subscription billing is not configured")


def _decimal_amount(value: Decimal) -> str:
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


def _subscription_description(organization_id: UUID) -> str:
    return f"Zahlmeister Pro {str(organization_id)[:8]}"


def _add_year(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, month=2, day=28)


def _end_of_date(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=UTC)


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
        raise MollieBillingUnavailable("Mollie subscription billing is unavailable") from exc
    if response.status_code >= 400:
        logger.warning("Mollie billing request failed: method=%s status=%s", method, response.status_code)
        raise MollieBillingUnavailable("Mollie subscription billing is unavailable")
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


async def _ensure_customer(
    organization_id: UUID,
    name: str,
    email: str,
    data: dict[str, Any],
) -> str:
    existing = data.get("mollie_customer_id")
    if isinstance(existing, str) and existing.startswith("cst_"):
        return existing
    customer = await _request_json(
        "POST",
        "customers",
        json_body={
            "name": name[:255],
            "email": email,
            "metadata": {
                "purpose": "zahlmeister_billing_customer",
                "organization_id": str(organization_id),
            },
        },
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
        "grace_until",
    ):
        data.pop(key, None)


async def _apply_failed_renewal(
    session: AsyncSession,
    row: StoreSubscription,
    data: dict[str, Any],
    remote_status: str,
) -> None:
    now = datetime.now(UTC)
    grace_until = _grace_expiry(data, row.expires_at, now=now)
    row.expires_at = grace_until
    row.last_verified_at = now
    if grace_until <= now:
        row.status = "expired"
        row.auto_renew = False
        row.cancelled_at = row.cancelled_at or now
    elif remote_status == "canceled":
        row.status = "cancelled"
        row.auto_renew = False
        row.cancelled_at = row.cancelled_at or now
    else:
        row.status = "grace_period"
        row.auto_renew = remote_status in {"active", "pending"}
    row.verification_data_encrypted = encrypt_config(data)
    await session.flush()


async def start_checkout(
    session: AsyncSession,
    organization_id: UUID,
    *,
    customer_name: str,
    customer_email: str,
) -> MollieCheckout:
    _require_configured()
    existing = await _mollie_row(session, organization_id, lock=True)
    if existing is not None:
        data = _verification_data(existing)
        subscription_id = data.get("subscription_id")
        customer_id = data.get("mollie_customer_id")
        if isinstance(subscription_id, str) and isinstance(customer_id, str):
            await _reconcile_subscription(session, existing, data)

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

    customer_id = await _ensure_customer(organization_id, customer_name, customer_email, data)
    _reset_finished_subscription_data(data)
    billing_amount, billing_currency = _current_billing_terms()
    checkout_attempt = str(uuid4())
    payment_payload: dict[str, Any] = {
        "amount": {"currency": billing_currency, "value": billing_amount},
        "description": "Zahlmeister Pro",
        "sequenceType": "first",
        "redirectUrl": _return_url("return"),
        "cancelUrl": _return_url("cancelled"),
        "metadata": _metadata(organization_id),
    }
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
    elif sequence_type == "recurring":
        subscription_id = payment.get("subscriptionId")
        if not isinstance(subscription_id, str) or data.get("subscription_id") != subscription_id:
            raise MollieBillingVerificationError("Mollie recurring payment is not linked to this subscription")
        await _process_recurring_payment(session, row, data, payment)
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

    existing_subscription_id = data.get("subscription_id")
    customer_id = data.get("mollie_customer_id")
    if isinstance(existing_subscription_id, str) and isinstance(customer_id, str):
        await _reconcile_subscription(session, row, data)
        return

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
    first_renewal_date = _add_year(paid_at.date())
    billing_amount, billing_currency = _stored_billing_terms(data)
    subscription_payload: dict[str, Any] = {
        "amount": {"currency": billing_currency, "value": billing_amount},
        "interval": MOLLIE_INTERVAL,
        "startDate": first_renewal_date.isoformat(),
        "description": _subscription_description(row.organization_id),
        "mandateId": mandate_id,
        "metadata": _metadata(row.organization_id),
    }
    webhook_url = _webhook_url()
    if webhook_url:
        subscription_payload["webhookUrl"] = webhook_url
    subscription = await _request_json(
        "POST",
        f"customers/{remote_customer_id}/subscriptions",
        json_body=subscription_payload,
        idempotency_key=f"zahlmeister-subscription-{payment_id}",
    )
    subscription_id = subscription.get("id")
    if not isinstance(subscription_id, str) or not subscription_id.startswith("sub_"):
        raise MollieBillingUnavailable("Mollie subscription creation failed")

    next_payment_date = _parse_date(subscription.get("nextPaymentDate")) or first_renewal_date
    data.update(
        {
            "mandate_id": mandate_id,
            "subscription_id": subscription_id,
            "last_payment_id": payment_id,
            "last_payment_status": "paid",
            "subscription_status": str(subscription.get("status", "active")),
        }
    )
    data.pop("grace_until", None)
    await apply_verified_subscription(
        session,
        row.organization_id,
        VerifiedSubscription(
            provider=MOLLIE_PROVIDER,
            product_id=PRO_PRODUCT_ID,
            external_reference=subscription_id,
            account_token=str(row.organization_id),
            status="active",
            purchased_at=paid_at,
            expires_at=_end_of_date(next_payment_date),
            auto_renew=True,
            environment=settings.mollie_billing_environment,
            verification_data=data,
        ),
    )


async def _process_recurring_payment(
    session: AsyncSession,
    row: StoreSubscription,
    data: dict[str, Any],
    payment: dict[str, Any],
) -> None:
    payment_id = str(payment["id"])
    payment_status = str(payment.get("status", ""))
    data.update({"last_payment_id": payment_id, "last_payment_status": payment_status})
    customer_id = data.get("mollie_customer_id")
    subscription_id = data.get("subscription_id")
    if not isinstance(customer_id, str) or not isinstance(subscription_id, str):
        raise MollieBillingVerificationError("Stored Mollie subscription binding is incomplete")

    subscription = await _get_subscription(customer_id, subscription_id)
    remote_status = str(subscription.get("status", ""))
    data["subscription_status"] = remote_status
    if payment_status == "paid":
        paid_at = _parse_datetime(payment.get("paidAt")) or datetime.now(UTC)
        next_payment = _parse_date(subscription.get("nextPaymentDate")) or _add_year(paid_at.date())
        mapped_status = "active" if remote_status == "active" else _map_subscription_status(remote_status)
        data.pop("grace_until", None)
        await apply_verified_subscription(
            session,
            row.organization_id,
            VerifiedSubscription(
                provider=MOLLIE_PROVIDER,
                product_id=PRO_PRODUCT_ID,
                external_reference=subscription_id,
                account_token=str(row.organization_id),
                status=mapped_status,
                purchased_at=row.purchased_at or paid_at,
                expires_at=_end_of_date(next_payment),
                auto_renew=remote_status == "active",
                environment=settings.mollie_billing_environment,
                verification_data=data,
            ),
        )
        return

    if payment_status in FAILED_PAYMENT_STATUSES and remote_status in {"active", "pending", "canceled"}:
        await _apply_failed_renewal(session, row, data, remote_status)
        return
    if remote_status in {"canceled", "completed", "suspended"}:
        await _apply_remote_subscription_status(session, row, data, subscription)
    else:
        row.last_verified_at = datetime.now(UTC)
        row.verification_data_encrypted = encrypt_config(data)
        await session.flush()


def _map_subscription_status(status: str) -> str:
    return {
        "active": "active",
        "pending": "pending",
        "canceled": "cancelled",
        "completed": "expired",
        "suspended": "on_hold",
    }.get(status, "on_hold")


async def _apply_remote_subscription_status(
    session: AsyncSession,
    row: StoreSubscription,
    data: dict[str, Any],
    subscription: dict[str, Any],
) -> None:
    remote_status = str(subscription.get("status", ""))
    mapped = _map_subscription_status(remote_status)
    data["subscription_status"] = remote_status
    row.status = mapped
    row.auto_renew = remote_status == "active"
    row.last_verified_at = datetime.now(UTC)
    if mapped in {"cancelled", "expired"}:
        row.cancelled_at = row.cancelled_at or datetime.now(UTC)
    row.verification_data_encrypted = encrypt_config(data)
    await session.flush()


async def _reconcile_subscription(
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
    if latest is None:
        await _apply_remote_subscription_status(session, row, data, subscription)
        return

    metadata_org = _verified_metadata(latest)
    if metadata_org != row.organization_id:
        raise MollieBillingVerificationError("Mollie subscription payment account binding is invalid")
    payment_subscription_id = latest.get("subscriptionId")
    if payment_subscription_id not in {None, subscription_id}:
        raise MollieBillingVerificationError("Mollie subscription payment binding is invalid")
    billing_amount, billing_currency = _stored_billing_terms(data)
    if not _payment_amount_matches(latest, billing_amount, billing_currency):
        raise MollieBillingVerificationError("Mollie subscription payment amount is invalid")

    payment_status = str(latest.get("status", ""))
    data.update(
        {
            "last_payment_id": latest.get("id"),
            "last_payment_status": payment_status,
            "subscription_status": remote_status,
        }
    )
    if payment_status == "paid":
        paid_at = _parse_datetime(latest.get("paidAt")) or datetime.now(UTC)
        next_payment = _parse_date(subscription.get("nextPaymentDate")) or _add_year(paid_at.date())
        mapped_status = "active" if remote_status == "active" else _map_subscription_status(remote_status)
        data.pop("grace_until", None)
        await apply_verified_subscription(
            session,
            row.organization_id,
            VerifiedSubscription(
                provider=MOLLIE_PROVIDER,
                product_id=PRO_PRODUCT_ID,
                external_reference=subscription_id,
                account_token=str(row.organization_id),
                status=mapped_status,
                purchased_at=row.purchased_at or paid_at,
                expires_at=_end_of_date(next_payment),
                auto_renew=remote_status == "active",
                environment=settings.mollie_billing_environment,
                verification_data=data,
            ),
        )
        return
    if payment_status in FAILED_PAYMENT_STATUSES and remote_status in {"active", "pending", "canceled"}:
        await _apply_failed_renewal(session, row, data, remote_status)
        return
    if remote_status in {"canceled", "completed", "suspended"}:
        await _apply_remote_subscription_status(session, row, data, subscription)
        return
    row.last_verified_at = datetime.now(UTC)
    row.verification_data_encrypted = encrypt_config(data)
    await session.flush()


async def sync_subscription(session: AsyncSession, organization_id: UUID) -> None:
    _require_configured()
    row = await _mollie_row(session, organization_id, lock=True)
    if row is None:
        return
    data = _verification_data(row)
    if isinstance(data.get("subscription_id"), str):
        await _reconcile_subscription(session, row, data)
        return
    payment_id = data.get("initial_payment_id")
    if isinstance(payment_id, str):
        payment = await _get_payment(payment_id)
        await _process_payment_payload(session, payment)


async def cancel_subscription(session: AsyncSession, organization_id: UUID) -> None:
    _require_configured()
    row = await _mollie_row(session, organization_id, lock=True)
    if row is None:
        raise MollieBillingConflict("No Mollie subscription exists")
    data = _verification_data(row)
    customer_id = data.get("mollie_customer_id")
    subscription_id = data.get("subscription_id")
    if not isinstance(customer_id, str) or not isinstance(subscription_id, str):
        raise MollieBillingConflict("No active Mollie subscription exists")
    subscription = await _request_json(
        "DELETE",
        f"customers/{customer_id}/subscriptions/{subscription_id}",
    )
    if not subscription:
        subscription = {"status": "canceled"}
    await _apply_remote_subscription_status(session, row, data, subscription)
