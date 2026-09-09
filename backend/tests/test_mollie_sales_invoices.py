from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.billing import BillingInvoice, BillingProfile
from app.services import mollie_billing_core as core


def _invoice(*, kind: str = "initial_receipt") -> BillingInvoice:
    now = datetime(2026, 9, 8, tzinfo=UTC)
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
        vat_rate=Decimal("20.0"),
        vat_scheme="standard",
        tax_treatment="domestic_standard",
        recipient_country="AT",
        recipient_type="consumer",
        idempotency_key=uuid4(),
        status="creating",
        created_at=now,
        details_json=(
            f'{{"kind":"{kind}","tax_rule_version":"2026-09-08",'
            '"recipient":{"type":"consumer","givenName":"Test","familyName":"Customer",'
            '"email":"customer@example.test","streetAndNumber":"Example 1",'
            '"postalCode":"1010","city":"Vienna","country":"AT"}}'
        ),
    )


def _remote(item: BillingInvoice, *, status: str = "pending-payment") -> dict:
    return {
        "resource": "sales-invoice",
        "id": "invoice_test",
        "mode": "test",
        "status": status,
        "currency": item.currency,
        "vatScheme": item.vat_scheme,
        "recipientIdentifier": f"zahlmeister-{item.organization_id}",
        "recipient": {"type": item.recipient_type, "country": item.recipient_country},
        "memo": core._invoice_reference(item),
        "lines": [{
            "quantity": 1,
            "vatRate": f"{Decimal(item.vat_rate):.2f}",
            "unitPrice": {"currency": item.currency, "value": f"{Decimal(item.gross_amount):.2f}"},
        }],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["initial_receipt", "renewal_receipt"])
async def test_paid_period_receipts_never_create_a_second_charge(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    captured = {}

    async def fake_request(method, path, *, json_body=None, params=None, idempotency_key=None):
        captured.update(method=method, path=path, json_body=json_body, idempotency_key=idempotency_key)
        return {"id": "invoice_test", "status": "paid"}

    monkeypatch.setattr(core, "_request_json", fake_request)
    item = _invoice(kind=kind)
    await core._create_remote_receipt(item, "de-AT")
    body = captured["json_body"]
    assert captured["method"] == "POST"
    assert captured["path"] == "sales-invoices"
    assert body["status"] == "paid"
    assert body["paymentDetails"] == {"source": "manual"}
    assert "customerId" not in body
    assert "mandateId" not in body
    assert body["vatMode"] == "inclusive"
    assert body["lines"][0]["unitPrice"] == {"currency": "EUR", "value": "29.90"}
    assert body["lines"][0]["vatRate"] == "20.00"
    assert core._invoice_reference(item) in body["memo"]


def test_mollie_invoice_status_variants_are_normalized() -> None:
    assert core._normalize_sales_invoice_status("payment_reversed") == "payment-reversed"
    assert core._normalize_sales_invoice_status("payment-reversed") == "payment-reversed"
    assert core._normalize_sales_invoice_status("canceled") == "cancelled"


@pytest.mark.asyncio
async def test_recovery_finds_remote_invoice_before_any_new_post(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _invoice(kind="renewal_receipt")
    remote = _remote(item)
    calls = []

    async def fake_request(method, path, *, json_body=None, params=None, idempotency_key=None):
        calls.append((method, path, params))
        return {"_embedded": {"salesInvoices": [remote]}, "_links": {"next": None}}

    monkeypatch.setattr(core, "_request_json", fake_request)
    assert await core._find_remote_invoice(item) == remote
    assert calls == [("GET", "sales-invoices", {"limit": 250})]


def test_business_invoice_recipient_requires_tax_or_organization_identifier() -> None:
    profile = BillingProfile(
        customer_type="business",
        organization_name="Example GmbH",
        billing_email="billing@example.test",
        street_and_number="Example 1",
        postal_code="1010",
        city="Vienna",
        country="AT",
        vat_number="ATU12345678",
    )
    recipient = core._invoice_recipient(profile)
    assert recipient["type"] == "business"
    assert recipient["organizationName"] == "Example GmbH"
    assert recipient["vatNumber"] == "ATU12345678"
