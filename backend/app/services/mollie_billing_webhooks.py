from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.billing import BillingInvoice
from app.services.mollie_billing import (
    INVOICE_CREATE_RETRY_WINDOW,
    MOLLIE_PROVIDER,
    MollieBillingVerificationError,
    _apply_invoice_payload,
    _get_sales_invoice,
    _invoice_reference,
    _normalize_utc,
    _parse_datetime,
)


class MollieBillingWebhookError(RuntimeError):
    pass


def verify_sales_invoice_signature(raw_body: bytes, signature: str | None) -> None:
    secret = settings.mollie_billing_webhook_secret.strip()
    if not secret:
        raise MollieBillingWebhookError("Mollie billing webhook secret is not configured")
    if not signature:
        raise MollieBillingWebhookError("Mollie billing webhook signature is missing")
    supplied = signature.removeprefix("sha256=").strip().lower()
    if len(supplied) != 64 or any(character not in "0123456789abcdef" for character in supplied):
        raise MollieBillingWebhookError("Mollie billing webhook signature is invalid")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise MollieBillingWebhookError("Mollie billing webhook signature is invalid")


def _reference_invoice_id(payload: dict) -> UUID | None:
    memo = payload.get("memo")
    if not isinstance(memo, str):
        return None
    for line in memo.splitlines():
        value = line.strip()
        if not value.startswith("ZM:"):
            continue
        try:
            return UUID(value.removeprefix("ZM:").strip())
        except ValueError:
            return None
    return None


def _remote_invoice_matches_local(item: BillingInvoice, payload: dict) -> bool:
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
    if str(line.get("vatRate", "")) != f"{Decimal(item.vat_rate):.2f}":
        return False
    unit_price = line.get("unitPrice")
    if not isinstance(unit_price, dict):
        return False
    if str(unit_price.get("currency", "")).upper() != item.currency.upper():
        return False
    try:
        remote_amount = Decimal(str(unit_price.get("value", "")))
    except InvalidOperation:
        return False
    if remote_amount != Decimal(item.gross_amount):
        return False

    remote_created = _parse_datetime(payload.get("createdAt"))
    if remote_created is not None and item.created_at is not None:
        local_created = _normalize_utc(item.created_at)
        delta = remote_created - local_created
        if delta < timedelta(0) or delta > INVOICE_CREATE_RETRY_WINDOW + timedelta(minutes=5):
            return False
    return True


async def _recover_unbound_invoice(
    session: AsyncSession,
    payload: dict,
) -> BillingInvoice | None:
    local_id = _reference_invoice_id(payload)
    if local_id is None:
        return None
    item = await session.get(BillingInvoice, local_id, with_for_update=True)
    if item is None:
        return None
    if item.provider != MOLLIE_PROVIDER or item.status != "creating" or item.external_id is not None:
        return None
    if not _remote_invoice_matches_local(item, payload):
        raise MollieBillingWebhookError("Mollie sales invoice does not match its local invoice")
    return item


async def process_sales_invoice_webhook(
    session: AsyncSession,
    raw_body: bytes,
    signature: str | None,
) -> UUID | None:
    verify_sales_invoice_signature(raw_body, signature)
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MollieBillingWebhookError("Mollie billing webhook payload is invalid") from exc
    if not isinstance(payload, dict) or payload.get("resource") != "sales-invoice":
        raise MollieBillingWebhookError("Unexpected Mollie billing webhook resource")
    invoice_id = payload.get("id")
    if not isinstance(invoice_id, str) or not invoice_id.startswith("invoice_"):
        raise MollieBillingWebhookError("Mollie sales invoice reference is invalid")

    # The signed webhook only triggers a sync. Billing state is always derived from
    # a fresh authenticated Mollie API read, never from the webhook snapshot itself.
    verified = await _get_sales_invoice(invoice_id)
    item = await session.scalar(
        select(BillingInvoice)
        .where(
            BillingInvoice.provider == MOLLIE_PROVIDER,
            BillingInvoice.external_id == invoice_id,
        )
        .with_for_update()
    )
    if item is None:
        item = await _recover_unbound_invoice(session, verified)
        if item is None:
            return None

    try:
        await _apply_invoice_payload(session, item, verified)
    except MollieBillingVerificationError as exc:
        raise MollieBillingWebhookError("Mollie sales invoice verification failed") from exc
    return item.organization_id
