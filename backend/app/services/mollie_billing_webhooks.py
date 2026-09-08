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
)


class MollieBillingWebhookError(RuntimeError):
    pass


def verify_sales_invoice_signature(raw_body: bytes, signature: str | None) -> None:
    secret = settings.mollie_billing_webhook_secret.strip()
    if not secret:
        raise MollieBillingWebhookError("Mollie billing webhook secret is not configured")
    if not signature or not signature.startswith("sha256="):
        raise MollieBillingWebhookError("Mollie billing webhook signature is missing")
    supplied = signature.removeprefix("sha256=").strip().lower()
    if len(supplied) != 64:
        raise MollieBillingWebhookError("Mollie billing webhook signature is invalid")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise MollieBillingWebhookError("Mollie billing webhook signature is invalid")


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

    item = await session.scalar(
        select(BillingInvoice)
        .where(
            BillingInvoice.provider == MOLLIE_PROVIDER,
            BillingInvoice.external_id == invoice_id,
        )
        .with_for_update()
    )
    if item is None:
        # Never bind an unsolicited remote invoice to a Zahlmeister account.
        return None

    verified = await _get_sales_invoice(invoice_id)
    try:
        await _apply_invoice_payload(session, item, verified)
    except MollieBillingVerificationError as exc:
        raise MollieBillingWebhookError("Mollie sales invoice verification failed") from exc
    return item.organization_id
