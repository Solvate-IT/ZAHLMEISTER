import pytest

from app.services.billing_invoice_status import effective_invoice_status


@pytest.mark.parametrize("invoice_status", ["creating", "issuing", "pending-payment"])
def test_verified_paid_payment_hides_transient_receipt_status(invoice_status: str) -> None:
    assert effective_invoice_status(invoice_status, "paid") == "paid"


@pytest.mark.parametrize("invoice_status", ["issued", "overdue", "payment-reversed", "cancelled"])
def test_verified_paid_payment_does_not_hide_meaningful_invoice_status(invoice_status: str) -> None:
    assert effective_invoice_status(invoice_status, "paid") == invoice_status


def test_unpaid_payment_keeps_invoice_status() -> None:
    assert effective_invoice_status("pending-payment", "pending") == "pending-payment"
