from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.billing import BillingCycle, BillingInvoice, BillingPaymentTransaction
from app.services import mollie_billing_core as core
from app.services.mollie_billing_webhooks import verify_sales_invoice_signature


def _cycle() -> BillingCycle:
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    cycle_id = uuid4()
    return BillingCycle(
        id=cycle_id,
        organization_id=uuid4(),
        billing_key=f"ZM:{cycle_id}",
        operation="renewal",
        status="prepared",
        provider="mollie",
        provider_environment="test",
        product_id="zahlmeister.pro.yearly",
        tariff_version="2026-09-08",
        period_start=now,
        period_end=now + timedelta(days=365),
        gross_amount=Decimal("29.90"),
        currency="EUR",
        tax_rate=Decimal("20.000"),
        tax_scheme="standard",
        tax_treatment="domestic_standard",
        tax_rule_version="test-rule",
        recipient_json='{"type":"consumer","country":"AT"}',
    )


def _transaction(cycle: BillingCycle) -> BillingPaymentTransaction:
    return BillingPaymentTransaction(
        id=uuid4(),
        cycle_id=cycle.id,
        organization_id=cycle.organization_id,
        provider="mollie",
        provider_environment="test",
        attempt=1,
        status="reserved",
        sequence_type="recurring",
        gross_amount=Decimal("29.90"),
        currency="EUR",
    )


def test_payment_metadata_binds_cycle_and_transaction() -> None:
    cycle = _cycle()
    transaction = _transaction(cycle)
    metadata = core._payment_metadata(cycle.organization_id, cycle, transaction)
    assert metadata["organization_id"] == str(cycle.organization_id)
    assert metadata["billing_key"] == cycle.billing_key
    assert metadata["billing_cycle_id"] == str(cycle.id)
    assert metadata["payment_transaction_id"] == str(transaction.id)


def test_invoice_amounts_are_immutable_net_tax_gross_split() -> None:
    net, tax = core._invoice_amounts(Decimal("29.90"), Decimal("20.000"))
    assert net == Decimal("24.92")
    assert tax == Decimal("4.98")
    assert net + tax == Decimal("29.90")


@pytest.mark.asyncio
async def test_payment_recovery_is_fail_closed_when_pagination_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle = _cycle()
    transaction = _transaction(cycle)
    calls = 0

    async def fake_request(method, path, *, json_body=None, params=None, idempotency_key=None):
        nonlocal calls
        calls += 1
        return {
            "_embedded": {"payments": []},
            "_links": {"next": {"href": f"https://api.mollie.com/v2/payments?from=next-{calls}"}},
        }

    monkeypatch.setattr(core, "_request_json", fake_request)
    monkeypatch.setattr(core, "MAX_PAYMENT_RECOVERY_PAGES", 2)

    with pytest.raises(core.MollieBillingUnavailable, match="recovery scan is incomplete"):
        await core._find_remote_payment(transaction, cycle, "cst_example")
    assert calls == 2


@pytest.mark.asyncio
async def test_payment_recovery_finds_exact_later_page_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle = _cycle()
    transaction = _transaction(cycle)
    expected = {
        "id": "tr_example",
        "sequenceType": "recurring",
        "customerId": "cst_example",
        "amount": {"currency": "EUR", "value": "29.90"},
        "metadata": core._payment_metadata(cycle.organization_id, cycle, transaction),
    }
    calls = 0

    async def fake_request(method, path, *, json_body=None, params=None, idempotency_key=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "_embedded": {"payments": []},
                "_links": {"next": {"href": "https://api.mollie.com/v2/payments?from=page-2"}},
            }
        return {"_embedded": {"payments": [expected]}, "_links": {}}

    monkeypatch.setattr(core, "_request_json", fake_request)
    assert await core._find_remote_payment(transaction, cycle, "cst_example") == expected
    assert calls == 2


def test_paid_receipt_model_links_payment_and_cycle() -> None:
    cycle = _cycle()
    transaction = _transaction(cycle)
    invoice = BillingInvoice(
        organization_id=cycle.organization_id,
        billing_cycle_id=cycle.id,
        payment_transaction_id=transaction.id,
        provider="mollie",
        product_id=cycle.product_id,
        tariff_version=cycle.tariff_version,
        period_start=cycle.period_start,
        period_end=cycle.period_end,
        net_amount=Decimal("24.92"),
        tax_amount=Decimal("4.98"),
        gross_amount=Decimal("29.90"),
        currency="EUR",
        vat_rate=Decimal("20.000"),
        vat_scheme="standard",
        tax_treatment="domestic_standard",
        recipient_country="AT",
        recipient_type="consumer",
        status="creating",
        details_json="{}",
    )
    assert invoice.billing_cycle_id == cycle.id
    assert invoice.payment_transaction_id == transaction.id
    assert invoice.net_amount + invoice.tax_amount == invoice.gross_amount


def test_multiple_webhook_signatures_accept_any_matching_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import hmac

    from app.core.config import settings

    secret = "s" * 64
    body = b'{"resource":"sales-invoice","id":"invoice_example"}'
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(settings, "mollie_billing_webhook_secret", secret)
    verify_sales_invoice_signature(body, ["0" * 64, expected])
