import pytest
from pydantic import ValidationError

from app.schemas.billing import BillingProfileWrite


def _business(**overrides) -> dict:
    values = {
        "customer_type": "business",
        "organization_name": "Example GmbH",
        "billing_email": "billing@example.test",
        "street_and_number": "Example 1",
        "postal_code": "1010",
        "city": "Vienna",
        "country": "AT",
        "vat_number": "ATU12345678",
    }
    values.update(overrides)
    return values


def test_business_profile_requires_tax_or_registration_identifier() -> None:
    with pytest.raises(ValidationError):
        BillingProfileWrite.model_validate(
            _business(vat_number=None, organization_number=None)
        )


def test_business_profile_accepts_vat_identifier() -> None:
    profile = BillingProfileWrite.model_validate(_business())
    assert profile.vat_number == "ATU12345678"


def test_business_profile_accepts_organization_number_without_vat() -> None:
    profile = BillingProfileWrite.model_validate(
        _business(vat_number=None, organization_number="FN 123456a")
    )
    assert profile.organization_number == "FN 123456a"
