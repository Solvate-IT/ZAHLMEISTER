import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.billing import BillingInvoice
from app.services.mollie_billing import _invoice_reference
from app.services.mollie_billing_webhooks import (
    MollieBillingWebhookError,
    _reference_invoice_id,
    _remote_invoice_matches_local,
    verify_sales_invoice_signature,
)


def _signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _invoice() -> BillingInvoice:
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    return BillingInvoice(
        id=uuid4(),
        organization_id=uuid4(),
        provider="mollie",
        product_id="zahlmeister.pro.yearly",
        tariff_version="2026-09-08",
        period_start=now,
        period_end=now.replace(year=2027),
        gross_amount=Decimal("29.90"),
        currency="EUR",
        vat_rate=Decimal("20.00"),
        vat_scheme="standard",
        tax_treatment="domestic_standard",
        recipient_country="AT",
        recipient_type="consumer",
        idempotency_key=uuid4(),
        status="creating",
        created_at=now,
        details_json="{}",
    )


def _remote(item: BillingInvoice) -> dict:
    return {
        "resource": "sales-invoice",
        "id": "invoice_example",
        "mode": settings.mollie_billing_environment,
        "status": "pending-payment",
        "currency": "EUR",
        "vatScheme": "standard",
        "recipientIdentifier": f"zahlmeister-{item.organization_id}",
        "recipient": {"type": "consumer", "country": "AT"},
        "memo": _invoice_reference(item),
        "createdAt": (item.created_at + timedelta(minutes=10)).isoformat(),
        "lines": [
            {
                "quantity": 1,
                "vatRate": "20.00",
                "unitPrice": {"currency": "EUR", "value": "29.90"},
            }
        ],
    }


def test_valid_sales_invoice_webhook_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "a" * 64
    body = b'{"resource":"sales-invoice","id":"invoice_example","status":"paid"}'
    monkeypatch.setattr(settings, "mollie_billing_webhook_secret", secret)
    verify_sales_invoice_signature(body, _signature(secret, body))


def test_optional_sha256_prefix_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "a" * 64
    body = b'{"resource":"sales-invoice","id":"invoice_example","status":"paid"}'
    monkeypatch.setattr(settings, "mollie_billing_webhook_secret", secret)
    verify_sales_invoice_signature(body, f"sha256={_signature(secret, body)}")


@pytest.mark.parametrize("signature", [None, "", "invalid", "sha256=1234", "z" * 64])
def test_invalid_sales_invoice_webhook_signature_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    signature: str | None,
) -> None:
    monkeypatch.setattr(settings, "mollie_billing_webhook_secret", "a" * 64)
    with pytest.raises(MollieBillingWebhookError):
        verify_sales_invoice_signature(b"{}", signature)


def test_modified_webhook_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "b" * 64
    original = b'{"resource":"sales-invoice","id":"invoice_example","status":"paid"}'
    modified = b'{"resource":"sales-invoice","id":"invoice_example","status":"issued"}'
    monkeypatch.setattr(settings, "mollie_billing_webhook_secret", secret)
    with pytest.raises(MollieBillingWebhookError):
        verify_sales_invoice_signature(modified, _signature(secret, original))


def test_remote_invoice_reference_recovers_exact_local_invoice() -> None:
    item = _invoice()
    payload = _remote(item)
    assert _reference_invoice_id(payload) == item.id
    assert _remote_invoice_matches_local(item, payload) is True


def test_remote_invoice_recovery_rejects_wrong_amount() -> None:
    item = _invoice()
    payload = _remote(item)
    payload["lines"][0]["unitPrice"]["value"] = "0.01"
    assert _remote_invoice_matches_local(item, payload) is False


def test_remote_invoice_recovery_rejects_wrong_local_reference() -> None:
    item = _invoice()
    payload = _remote(item)
    payload["memo"] = f"ZM:{uuid4()}"
    assert _remote_invoice_matches_local(item, payload) is False


def test_remote_invoice_recovery_rejects_creation_outside_retry_window() -> None:
    item = _invoice()
    payload = _remote(item)
    payload["createdAt"] = (item.created_at + timedelta(hours=2)).isoformat()
    assert _remote_invoice_matches_local(item, payload) is False
