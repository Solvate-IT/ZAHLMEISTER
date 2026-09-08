import hashlib
import hmac

import pytest

from app.core.config import settings
from app.services.mollie_billing_webhooks import (
    MollieBillingWebhookError,
    verify_sales_invoice_signature,
)


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_valid_sales_invoice_webhook_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "a" * 64
    body = b'{"resource":"sales-invoice","id":"invoice_example","status":"paid"}'
    monkeypatch.setattr(settings, "mollie_billing_webhook_secret", secret)
    verify_sales_invoice_signature(body, _signature(secret, body))


@pytest.mark.parametrize("signature", [None, "", "invalid", "sha256=1234"])
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
