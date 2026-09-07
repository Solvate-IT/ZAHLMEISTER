from decimal import Decimal

from app.services.payments import (
    epc_qr_payload,
    is_valid_iban,
    normalize_iban,
    public_payment_url,
)


def test_iban_validation_and_normalization() -> None:
    iban = "AT61 1904 3002 3457 3201"
    assert normalize_iban(iban) == "AT611904300234573201"
    assert is_valid_iban(iban)
    assert not is_valid_iban("AT001234")


def test_epc_qr_payload_contains_unstructured_reference() -> None:
    payload = epc_qr_payload(
        account_name="Max Muster",
        iban="AT611904300234573201",
        bic="BKAUATWW",
        amount=Decimal("12.50"),
        currency="EUR",
        reference="ZM-ABC123",
    )
    assert payload is not None
    lines = payload.splitlines()
    assert lines[:4] == ["BCD", "002", "1", "SCT"]
    assert "EUR12.50" in lines
    assert lines[10] == "ZM-ABC123"


def test_epc_qr_only_for_euro() -> None:
    assert epc_qr_payload(
        account_name="Max Muster",
        iban="AT611904300234573201",
        bic=None,
        amount=Decimal("10.00"),
        currency="USD",
        reference="ZM-1",
    ) is None


def test_public_payment_url_uses_query_token() -> None:
    assert public_payment_url("https://pay.example.com/", "abc_123") == (
        "https://pay.example.com/?pay=abc_123"
    )


def test_public_payment_qr_url_uses_public_api_endpoint() -> None:
    from app.services.payments import public_payment_qr_url

    assert public_payment_qr_url("https://pay.example.com/", "abc_123") == (
        "https://pay.example.com/api/v1/public/payments/abc_123/qr.png"
    )
