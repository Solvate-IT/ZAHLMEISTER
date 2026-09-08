from __future__ import annotations

import hashlib
import hmac
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.billing import BillingInvoice
from app.services.mollie_billing import (
    MOLLIE_PROVIDER,
    MollieBillingVerificationError,
    _apply_invoice_payload,
    _get_sales_invoice,
    _mollie_row,
    _reference_invoice_id,
    _remote_invoice_matches_local,
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


def _invoice_id_from_webhook_payload(payload: dict) -> str:
    if payload.get("resource") == "sales-invoice":
        invoice_id = payload.get("id")
    elif payload.get("resource") == "event" and str(payload.get("type", "")).startswith("sales-invoice."):
        invoice_id = payload.get("entityId")
        if not isinstance(invoice_id, str):
            embedded = payload.get("_embedded")
            entity = embedded.get("entity") if isinstance(embedded, dict) else None
            invoice_id = entity.get("id") if isinstance(entity, dict) else None
    else:
        raise MollieBillingWebhookError("Unexpected Mollie billing webhook resource")
    if not isinstance(invoice_id, str) or not invoice_id.startswith("invoice_"):
        raise MollieBillingWebhookError("Mollie sales invoice reference is invalid")
    return invoice_id


async def _locked_bound_invoice(
    session: AsyncSession,
    invoice_id: str,
) -> BillingInvoice | None:
    candidate = await session.scalar(
        select(BillingInvoice).where(
            BillingInvoice.provider == MOLLIE_PROVIDER,
            BillingInvoice.external_id == invoice_id,
        )
    )
    if candidate is None:
        return None
    await _mollie_row(session, candidate.organization_id, lock=True)
    return await session.get(BillingInvoice, candidate.id, with_for_update=True)


async def _recover_unbound_invoice(
    session: AsyncSession,
    payload: dict,
) -> BillingInvoice | None:
    local_id = _reference_invoice_id(payload)
    if local_id is None:
        return None
    candidate = await session.get(BillingInvoice, local_id)
    if candidate is None:
        return None
    await _mollie_row(session, candidate.organization_id, lock=True)
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
    if not isinstance(payload, dict):
        raise MollieBillingWebhookError("Mollie billing webhook payload is invalid")
    invoice_id = _invoice_id_from_webhook_payload(payload)

    # The signed webhook is only a trigger. Billing state is always derived from
    # a fresh authenticated Sales Invoice API read, never from the event snapshot.
    verified = await _get_sales_invoice(invoice_id)
    item = await _locked_bound_invoice(session, invoice_id)
    if item is None:
        item = await _recover_unbound_invoice(session, verified)
        if item is None:
            return None

    try:
        await _apply_invoice_payload(session, item, verified)
    except MollieBillingVerificationError as exc:
        raise MollieBillingWebhookError("Mollie sales invoice verification failed") from exc
    return item.organization_id
