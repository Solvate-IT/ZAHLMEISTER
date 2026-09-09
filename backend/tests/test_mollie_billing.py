from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

import app.core.config as config_module
from app.core.billing_catalog import BillingTariff, PRO_YEARLY_TARIFF
from app.core.config import settings
from app.services.billing import PRO_PRODUCT_ID
from app.services.mollie_billing_core import (
    MOLLIE_GRACE_DAYS,
    MOLLIE_PURPOSE,
    MollieBillingVerificationError,
    _grace_expiry,
    _metadata,
    _payment_amount_matches,
    _reset_finished_subscription_data,
    _stored_billing_terms,
    _verified_metadata,
    _webhook_url,
    amount_value,
    billing_config,
    billing_configured,
)


def _configure_test_billing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mollie_billing_api_key", "test_example")
    monkeypatch.setattr(settings, "mollie_billing_environment", "test")


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


def test_tariff_is_versioned_in_code() -> None:
    assert PRO_YEARLY_TARIFF.version == "2026-09-08"
    assert PRO_YEARLY_TARIFF.product_id == PRO_PRODUCT_ID
    assert PRO_YEARLY_TARIFF.amount == Decimal("29.90")
    assert PRO_YEARLY_TARIFF.currency == "EUR"
    assert PRO_YEARLY_TARIFF.interval == "12 months"


def test_billing_config_uses_versioned_tariff(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_test_billing(monkeypatch)
    config = billing_config()
    assert config["amount"] == "29.90"
    assert config["currency"] == "EUR"
    assert config["interval"] == "12 months"


def test_payment_must_match_exact_catalog_amount_and_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    assert _payment_amount_matches({"amount": {"value": "29.90", "currency": "EUR"}}) is True
    assert _payment_amount_matches({"amount": {"value": "29.89", "currency": "EUR"}}) is False
    assert _payment_amount_matches({"amount": {"value": "29.90", "currency": "USD"}}) is False


def test_existing_subscription_keeps_its_original_price_after_catalog_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = {"billing_amount": "29.90", "billing_currency": "EUR"}
    monkeypatch.setattr(
        config_module,
        "PRO_YEARLY_TARIFF",
        BillingTariff(
            version="future",
            product_id=PRO_PRODUCT_ID,
            amount=Decimal("39.90"),
            currency="EUR",
            interval="12 months",
        ),
    )
    amount, currency = _stored_billing_terms(stored)
    assert (amount, currency) == ("29.90", "EUR")
    assert amount_value() == "39.90"
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
        "mandate_id": "mdt_old",
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

