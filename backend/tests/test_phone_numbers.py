import pytest

from app.services.phone_numbers import normalize_phone_number, preferred_phone_region


@pytest.mark.parametrize(
    ("value", "region", "expected"),
    [
        ("0660 1234567", "AT", "+436601234567"),
        ("0043 660 1234567", "AT", "+436601234567"),
        ("+49 (151) 23456789", "AT", "+4915123456789"),
        ("0151 23456789", "DE", "+4915123456789"),
        ("  ", "AT", None),
    ],
)
def test_numbers_are_stored_in_e164(value: str, region: str, expected: str | None) -> None:
    assert normalize_phone_number(value, region) == expected


@pytest.mark.parametrize("value", ["123", "abc", "0660 1234567 ext 12"])
def test_invalid_or_ambiguous_numbers_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid phone number"):
        normalize_phone_number(value, "AT")


def test_country_precedence_and_austrian_fallback() -> None:
    assert preferred_phone_region("de-AT", "DE") == "DE"
    assert preferred_phone_region("fr-FR") == "FR"
    assert preferred_phone_region("de") == "AT"
    assert preferred_phone_region("en", "XX") == "AT"
