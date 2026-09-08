from decimal import Decimal

import pytest

from app.models.billing import BillingProfile
from app.services import billing_tax
from app.services.billing_tax import (
    BillingTaxInvalidVatNumber,
    BillingTaxUnsupportedJurisdiction,
    tax_decision,
)


def _profile(**values) -> BillingProfile:
    defaults = {
        "customer_type": "consumer",
        "billing_email": "customer@example.test",
        "street_and_number": "Example 1",
        "postal_code": "1010",
        "city": "Vienna",
        "country": "AT",
        "given_name": "Test",
        "family_name": "Customer",
    }
    defaults.update(values)
    return BillingProfile(**defaults)


@pytest.mark.asyncio
async def test_austrian_customer_uses_domestic_standard_vat() -> None:
    decision = await tax_decision(_profile())
    assert decision.rate == Decimal("20.0")
    assert decision.vat_scheme == "standard"
    assert decision.treatment == "domestic_standard"


@pytest.mark.asyncio
async def test_eu_consumer_uses_destination_vat_and_oss() -> None:
    decision = await tax_decision(_profile(country="DE"))
    assert decision.rate == Decimal("19.0")
    assert decision.vat_scheme == "one-stop-shop"
    assert decision.treatment == "eu_oss_consumer"


@pytest.mark.asyncio
async def test_eu_business_uses_reverse_charge_only_after_vies_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def valid(_: str) -> bool:
        return True

    monkeypatch.setattr(billing_tax, "validate_vies_vat_number", valid)
    decision = await tax_decision(
        _profile(
            customer_type="business",
            given_name=None,
            family_name=None,
            organization_name="Example GmbH",
            country="DE",
            vat_number="DE123456789",
        )
    )
    assert decision.rate == Decimal("0.0")
    assert decision.vat_scheme == "standard"
    assert decision.treatment == "eu_reverse_charge"
    assert decision.vat_validation_status == "valid"
    assert decision.vat_validated_at is not None


@pytest.mark.asyncio
async def test_eu_business_without_valid_vat_number_is_not_reverse_charged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def invalid(_: str) -> bool:
        return False

    monkeypatch.setattr(billing_tax, "validate_vies_vat_number", invalid)
    with pytest.raises(BillingTaxInvalidVatNumber):
        await tax_decision(
            _profile(
                customer_type="business",
                given_name=None,
                family_name=None,
                organization_name="Example GmbH",
                country="DE",
                vat_number="DE123456789",
            )
        )


@pytest.mark.asyncio
async def test_vat_country_must_match_billing_country() -> None:
    with pytest.raises(BillingTaxInvalidVatNumber):
        await tax_decision(
            _profile(
                customer_type="business",
                given_name=None,
                family_name=None,
                organization_name="Example GmbH",
                country="DE",
                vat_number="ATU12345678",
            )
        )


@pytest.mark.asyncio
async def test_unsupported_country_is_blocked_instead_of_assuming_zero_tax() -> None:
    with pytest.raises(BillingTaxUnsupportedJurisdiction):
        await tax_decision(_profile(country="US"))
