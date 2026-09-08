import pytest
from pydantic import ValidationError

from app.schemas.payments import PaymentSettingsUpdate
from app.schemas.workflow import CollectionCreate


def test_payment_settings_require_link_or_qr() -> None:
    with pytest.raises(ValidationError):
        PaymentSettingsUpdate(
            account_name="Max Muster",
            iban="AT611904300234573201",
            include_payment_link=False,
            include_payment_qr=False,
        )


def test_payment_settings_default_to_link_only() -> None:
    settings = PaymentSettingsUpdate(
        account_name="Max Muster",
        iban="AT611904300234573201",
    )
    assert settings.include_payment_link is True
    assert settings.include_payment_qr is False


def test_collection_can_override_message_options() -> None:
    payload = CollectionCreate(
        participant_list_id="35339f45-b856-4f3c-a355-4a27a21f00d8",
        amount="12.00",
        include_payment_link=False,
        include_payment_qr=True,
    )
    assert payload.include_payment_link is False
    assert payload.include_payment_qr is True
