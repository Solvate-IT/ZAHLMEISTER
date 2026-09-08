from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services.billing import PRO_PRODUCT_ID
from app.services.mollie_billing import (
    MOLLIE_GRACE_DAYS,
    MOLLIE_PURPOSE,
    MollieBillingVerificationError,
    _add_year,
    _grace_expiry,
    _metadata,
    _payment_amount_matches,
    _reset_finished_subscription_data,
    _stored_billing_terms,
    _verified_metadata,
    _webhook_url,
    amount_value,
    billing_configured,
)


def _configure_test_billing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mollie_billing_api_key", "test_example")
    monkeypatch.setattr(settings, "mollie_billing_environment", "test")
    monkeypatch.setattr(settings, "mollie_billing_pro_yearly_amount", Decimal("99.90"))
    monkeypatch.setattr(settings, "mollie_billing_currency", "EUR")


def test_test_billing_requires_test_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_test_billing(monkeypatch)
    assert billing_configured() is True
    monkeypatch.setattr(settings, "mollie_billing_api_key", "live_example")
    assert billing_configured() is False


def test_live_billing_requires_live_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_test_billing(monkeypatch)
    monkeypatch.setattr(settings, "mollie_billing_environment", "live")
    assert billing_configured() is False
    monkeypatch.setattr(settings, "mollie_billing_api_key", "live_example")
    assert billing_configured() is True


def test_billing_is_disabled_without_positive_server_price(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_test_billing(monkeypatch)
    monkeypatch.setattr(settings, "mollie_billing_pro_yearly_amount", Decimal("0"))
    assert billing_configured() is False


def test_amount_is_server_controlled_and_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_test_billing(monkeypatch)
    monkeypatch.setattr(settings, "mollie_billing_pro_yearly_amount", Decimal("99.9"))
    assert amount_value() == "99.90"


def test_payment_must_match_exact_configured_amount_and_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    assert _payment_amount_matches({"amount": {"value": "99.90", "currency": "EUR"}}) is True
    assert _payment_amount_matches({"amount": {"value": "99.89", "currency": "EUR"}}) is False
    assert _payment_amount_matches({"amount": {"value": "99.90", "currency": "USD"}}) is False


def test_existing_subscription_keeps_its_original_price_after_price_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    stored = {"billing_amount": "29.90", "billing_currency": "EUR"}
    monkeypatch.setattr(settings, "mollie_billing_pro_yearly_amount", Decimal("39.90"))
    amount, currency = _stored_billing_terms(stored)
    assert (amount, currency) == ("29.90", "EUR")
    assert _payment_amount_matches(
        {"amount": {"value": "29.90", "currency": "EUR"}},
        amount,
        currency,
    ) is True


def test_renewal_grace_period_is_anchored_and_does_not_roll_forward() -> None:
    paid_through = datetime(2026, 9, 8, 23, 59, tzinfo=UTC)
    data: dict[str, str] = {}
    first = _grace_expiry(data, paid_through, now=paid_through)
    second = _grace_expiry(data, first, now=paid_through + timedelta(days=5))
    assert first == paid_through + timedelta(days=MOLLIE_GRACE_DAYS)
    assert second == first


def test_new_checkout_clears_finished_subscription_state_but_keeps_customer() -> None:
    data = {
        "mollie_customer_id": "cst_example",
        "subscription_id": "sub_old",
        "mandate_id": "mdt_old",
        "subscription_status": "canceled",
        "initial_payment_id": "tr_old",
        "billing_amount": "29.90",
        "billing_currency": "EUR",
        "grace_until": "2026-09-15T23:59:00+00:00",
    }
    _reset_finished_subscription_data(data)
    assert data == {"mollie_customer_id": "cst_example"}


def test_local_development_does_not_send_unreachable_mollie_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "oauth_callback_base_url", "http://localhost:8003")
    assert _webhook_url() is None


def test_public_callback_generates_mollie_webhook_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "oauth_callback_base_url", "https://zahlmeister.solvate.at")
    assert _webhook_url() == "https://zahlmeister.solvate.at/api/v1/billing/mollie/webhook"


def test_payment_metadata_binds_purchase_to_organization() -> None:
    organization_id = uuid4()
    metadata = _metadata(organization_id)
    assert metadata == {
        "purpose": MOLLIE_PURPOSE,
        "organization_id": str(organization_id),
        "product_id": PRO_PRODUCT_ID,
    }
    assert _verified_metadata({"metadata": metadata}) == organization_id


def test_invalid_payment_metadata_is_rejected() -> None:
    with pytest.raises(MollieBillingVerificationError):
        _verified_metadata(
            {
                "metadata": {
                    "purpose": "other",
                    "organization_id": str(uuid4()),
                    "product_id": PRO_PRODUCT_ID,
                }
            }
        )


def test_annual_renewal_handles_leap_day() -> None:
    assert _add_year(date(2028, 2, 29)) == date(2029, 2, 28)
