from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.billing import BillingInvoice, BillingProfile
from app.models.platform import StoreSubscription
from app.services import mollie_billing
from app.services.billing_tax import TaxDecision
from app.services.mollie_billing import (
    _apply_invoice_entitlement,
    _cancel_renewal_invoices,
    _create_due_renewal,
    _create_remote_invoice,
    _find_remote_invoice,
    _invoice_create_retry_allowed,
    _invoice_recipient,
    _invoice_reference,
    _normalize_sales_invoice_status,
    _retry_local_invoice,
)


def _invoice(*, kind: str = "initial") -> BillingInvoice:
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
        "memo": _invoice_reference(item),
        "lines": [
            {
                "quantity": 1,
                "vatRate": f"{Decimal(item.vat_rate):.2f}",
                "unitPrice": {"currency": item.currency, "value": f"{Decimal(item.gross_amount):.2f}"},
            }
        ],
    }


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
    assert _invoice_reference(item) in body["memo"]
    assert body["lines"][0]["description"] == "Zahlmeister Pro – 12 Monate"


@pytest.mark.asyncio
async def test_renewal_invoice_uses_customer_and_mandate_for_automatic_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def fake_request(method, path, *, json_body=None, params=None, idempotency_key=None):
        captured.update(json_body=json_body, idempotency_key=idempotency_key)
        return {"id": "invoice_test", "status": "pending-payment"}

    monkeypatch.setattr(mollie_billing, "_request_json", fake_request)
    item = _invoice(kind="renewal")
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
    assert _invoice_reference(item) in body["memo"]


def test_invoice_retry_waits_for_local_commit_but_has_no_one_hour_dead_zone() -> None:
    item = _invoice()
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    item.created_at = now - timedelta(minutes=10)
    assert _invoice_create_retry_allowed(item, now=now) is True

    item.created_at = now - timedelta(hours=12)
    assert _invoice_create_retry_allowed(item, now=now) is True

    item.created_at = now - timedelta(seconds=10)
    assert _invoice_create_retry_allowed(item, now=now) is False

    item.created_at = now - timedelta(minutes=10)
    item.external_id = "invoice_existing"
    assert _invoice_create_retry_allowed(item, now=now) is False

    item.external_id = None
    item.status = "cancelled"
    assert _invoice_create_retry_allowed(item, now=now) is False


def test_mollie_invoice_status_variants_are_normalized() -> None:
    assert _normalize_sales_invoice_status("payment_reversed") == "payment-reversed"
    assert _normalize_sales_invoice_status("payment-reversed") == "payment-reversed"
    assert _normalize_sales_invoice_status("canceled") == "cancelled"


@pytest.mark.asyncio
async def test_recovery_finds_remote_invoice_before_any_new_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _invoice(kind="renewal")
    item.created_at = datetime.now(UTC) - timedelta(days=3)
    remote = _remote(item)
    calls = []

    async def fake_request(method, path, *, json_body=None, params=None, idempotency_key=None):
        calls.append((method, path, params))
        return {
            "_embedded": {"salesInvoices": [remote]},
            "_links": {"next": None},
        }

    monkeypatch.setattr(mollie_billing, "_request_json", fake_request)
    assert await _find_remote_invoice(item) == remote
    assert calls == [("GET", "sales-invoices", {"limit": 250})]


@pytest.mark.asyncio
async def test_retry_never_posts_renewal_after_auto_renew_was_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _invoice(kind="renewal")
    item.created_at = datetime.now(UTC) - timedelta(minutes=2)
    row = StoreSubscription(
        organization_id=item.organization_id,
        provider="mollie",
        product_id=item.product_id,
        status="cancelled",
        auto_renew=False,
    )

    async def no_remote(_item):
        return None

    async def fake_row(session, organization_id, *, lock=False):
        assert organization_id == item.organization_id
        return row

    class FakeSession:
        async def get(self, model, object_id):
            return None

        async def flush(self):
            return None

    async def should_not_create(*args, **kwargs):
        raise AssertionError("cancelled renewal must not create a remote invoice")

    monkeypatch.setattr(mollie_billing, "_find_remote_invoice", no_remote)
    monkeypatch.setattr(mollie_billing, "_mollie_row", fake_row)
    monkeypatch.setattr(mollie_billing, "_verification_data", lambda subscription: {})
    monkeypatch.setattr(mollie_billing, "_create_remote_invoice", should_not_create)

    await _retry_local_invoice(FakeSession(), item)
    assert item.status == "cancelled"


@pytest.mark.asyncio
async def test_due_renewal_keeps_original_contract_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization_id = uuid4()
    paid_through = datetime.now(UTC) - timedelta(minutes=1)
    row = StoreSubscription(
        organization_id=organization_id,
        provider="mollie",
        product_id="zahlmeister.pro.yearly",
        status="active",
        expires_at=paid_through,
        auto_renew=True,
    )
    data = {
        "paid_through": paid_through.isoformat(),
        "billing_amount": "29.90",
        "billing_currency": "EUR",
        "billing_tariff_version": "2026-09-08",
    }
    profile = BillingProfile(
        organization_id=organization_id,
        customer_type="consumer",
        given_name="Test",
        family_name="Customer",
        billing_email="customer@example.test",
        street_and_number="Example 1",
        postal_code="1010",
        city="Vienna",
        country="AT",
    )
    captured = {}
    item = _invoice(kind="renewal")
    item.organization_id = organization_id
    item.period_start = paid_through
    item.external_id = "invoice_existing"

    async def fake_profile(session, org_id):
        return profile

    async def fake_tax(_profile):
        return TaxDecision(
            rate=Decimal("20.0"),
            vat_scheme="standard",
            treatment="domestic_standard",
            rule_version="future-tax-version",
            vat_validation_status="not_required",
        )

    async def fake_record(session, org_id, **kwargs):
        captured.update(kwargs)
        return item

    async def fake_sync(session, invoice):
        return None

    monkeypatch.setattr(mollie_billing, "_load_profile", fake_profile)
    monkeypatch.setattr(mollie_billing, "_prepare_profile_tax", fake_tax)
    monkeypatch.setattr(mollie_billing, "_invoice_record", fake_record)
    monkeypatch.setattr(mollie_billing, "_sync_invoice_item", fake_sync)

    await _create_due_renewal(object(), row, data)
    assert captured["amount"] == "29.90"
    assert captured["currency"] == "EUR"
    assert captured["tariff_version"] == "2026-09-08"


@pytest.mark.asyncio
async def test_pending_renewal_keeps_pro_in_bounded_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period_start = datetime.now(UTC) - timedelta(hours=1)
    item = _invoice(kind="renewal")
    item.period_start = period_start
    item.period_end = period_start.replace(year=period_start.year + 1)
    item.status = "pending-payment"
    row = StoreSubscription(
        organization_id=item.organization_id,
        provider="mollie",
        product_id="zahlmeister.pro.yearly",
        status="active",
        external_reference="mdt_example",
        expires_at=period_start,
        auto_renew=True,
    )

    async def fake_row(session, organization_id, *, lock=False):
        assert organization_id == item.organization_id
        return row

    class FakeSession:
        async def flush(self):
            return None

    monkeypatch.setattr(mollie_billing, "_mollie_row", fake_row)
    monkeypatch.setattr(mollie_billing, "_verification_data", lambda subscription: {})
    monkeypatch.setattr(mollie_billing, "encrypt_config", lambda data: "{}")

    await _apply_invoice_entitlement(FakeSession(), item)

    assert row.status == "grace_period"
    assert row.expires_at == period_start + timedelta(days=mollie_billing.MOLLIE_GRACE_DAYS)
    assert row.auto_renew is True


@pytest.mark.asyncio
async def test_existing_remote_renewal_is_cancelled_before_subscription_is_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _invoice(kind="renewal")
    item.external_id = "invoice_test"
    item.status = "issued"
    patch_calls = []

    class Scalars:
        def all(self):
            return [item]

    class Result:
        def scalars(self):
            return Scalars()

    class FakeSession:
        async def execute(self, statement):
            return Result()

        async def get(self, model, object_id, with_for_update=False):
            return item

        async def flush(self):
            return None

    async def fake_get(invoice_id):
        return _remote(item, status="issued")

    async def fake_apply(session, invoice, payload):
        invoice.external_id = payload["id"]
        invoice.status = mollie_billing._normalize_sales_invoice_status(payload["status"])

    async def fake_request(method, path, *, json_body=None, params=None, idempotency_key=None):
        patch_calls.append((method, path, json_body))
        return _remote(item, status="cancelled")

    monkeypatch.setattr(mollie_billing, "_get_sales_invoice", fake_get)
    monkeypatch.setattr(mollie_billing, "_apply_invoice_payload", fake_apply)
    monkeypatch.setattr(mollie_billing, "_request_json", fake_request)

    await _cancel_renewal_invoices(FakeSession(), item.organization_id)
    assert patch_calls == [
        ("PATCH", "sales-invoices/invoice_test", {"status": "cancelled"})
    ]
    assert item.status == "cancelled"


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
