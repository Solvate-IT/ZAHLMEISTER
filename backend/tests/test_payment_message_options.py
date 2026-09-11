from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.routes.payment_settings import update_payment_settings
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


@pytest.mark.asyncio
async def test_payment_settings_are_committed_and_normalized() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.committed = False

        async def commit(self) -> None:
            self.committed = True

    organization = SimpleNamespace(
        bank_account_name=None,
        bank_iban=None,
        bank_bic=None,
        message_include_payment_link=True,
        message_include_payment_qr=False,
    )
    session = FakeSession()
    payload = PaymentSettingsUpdate(
        account_name="Max Muster",
        iban="AT61 1904 3002 3457 3201",
        bic="BKAUATWW",
    )

    result = await update_payment_settings(payload, organization, session)

    assert session.committed is True
    assert organization.bank_account_name == "Max Muster"
    assert organization.bank_iban == "AT611904300234573201"
    assert organization.bank_bic == "BKAUATWW"
    assert result.iban == "AT611904300234573201"


def test_collection_can_override_message_options() -> None:
    payload = CollectionCreate(
        participant_list_id="35339f45-b856-4f3c-a355-4a27a21f00d8",
        amount="12.00",
        include_payment_link=False,
        include_payment_qr=True,
    )
    assert payload.include_payment_link is False
    assert payload.include_payment_qr is True
