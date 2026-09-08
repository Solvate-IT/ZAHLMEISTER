from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services.billing import PRO_PRODUCT_ID
from app.services.mollie_billing import (
    MOLLIE_PURPOSE,
    MollieBillingVerificationError,
    _add_year,
    _metadata,
    _payment_amount_matches,
    _verified_metadata,
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
