from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.billing import BillingInvoice, BillingProfile
from app.services import mollie_billing
from app.services.mollie_billing import _create_remote_invoice, _invoice_recipient


def _invoice() -> BillingInvoice:
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
        details_json=(
            '{"kind":"initial","tax_rule_version":"2026-09-08",'
            '"recipient":{"type":"consumer","givenName":"Test","familyName":"Customer",'
            '"email":"customer@example.test","streetAndNumber":"Example 1",'
            '"postalCode":"1010","city":"Vienna","country":"AT"}}'
        ),
    )


@pytest.mark.asyncio
async def test_initial_paid_period_uses_documented_manual_receipt_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def fake_request(method, path, *, json_body=None, params=None, idempotency_key=None):
        captured.update(
            method=method,
            path=path,
            json_body=json_body,
            params=params,
            idempotency_key=idempotency_key,
        )
        return {"id": "invoice_test", "status": "paid"}

    monkeypatch.setattr(mollie_billing, "_request_json", fake_request)
    item = _invoice()
    await _create_remote_invoice(item, customer_id=None, mandate_id=None, locale="de-AT")
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


@pytest.mark.asyncio
async def test_renewal_invoice_uses_customer_and_mandate_for_automatic_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def fake_request(method, path, *, json_body=None, params=None, idempotency_key=None):
        captured.update(json_body=json_body, idempotency_key=idempotency_key)
        return {"id": "invoice_test", "status": "pending-payment"}

    monkeypatch.setattr(mollie_billing, "_request_json", fake_request)
    item = _invoice()
    await _create_remote_invoice(
        item,
        customer_id="cst_example",
        mandate_id="mdt_example",
        locale="en-GB",
    )
    body = captured["json_body"]
    assert body["status"] == "paid"
    assert body["customerId"] == "cst_example"
    assert body["mandateId"] == "mdt_example"
    assert "paymentDetails" not in body
    assert captured["idempotency_key"] == f"zahlmeister-invoice-{item.idempotency_key}"


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
    recipient = _invoice_recipient(profile)
    assert recipient["type"] == "business"
    assert recipient["organizationName"] == "Example GmbH"
    assert recipient["vatNumber"] == "ATU12345678"
