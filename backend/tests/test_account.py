import pytest
from pydantic import ValidationError

from app.schemas.account import ProfileUpdateRequest, ResetPasswordRequest
from app.schemas.auth import UserRead


def test_profile_currency_is_normalized() -> None:
    payload = ProfileUpdateRequest(
        display_name="  Anna   Muster  ",
        organization_name="  Muster   Verein  ",
        currency="eur",
    )
    assert payload.display_name == "Anna Muster"
    assert payload.organization_name == "Muster Verein"
    assert payload.currency == "EUR"


def test_reset_password_requires_minimum_length() -> None:
    with pytest.raises(ValidationError):
        ResetPasswordRequest(token="x" * 30, new_password="short")


def test_user_read_exposes_verification_state() -> None:
    user = UserRead(
        id="u1",
        email="anna@example.com",
        display_name="Anna",
        organization_id="o1",
        organization_name="Muster Verein",
        locale="de-AT",
        currency="EUR",
        email_verified=True,
    )
    assert user.email_verified is True
