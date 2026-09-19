from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def backend(path: str) -> str:
    return (ROOT / path).read_text()


def test_paid_mollie_invoice_keeps_immutable_seller_snapshot_and_email_delivery() -> None:
    core = backend("app/services/mollie_billing_core.py")

    assert '"seller": _seller_snapshot(seller)' in core
    assert '"emailDetails": {"subject": copy.email_subject, "body": copy.email_body}' in core
    assert 'idempotency_key=f"zahlmeister-invoice-{item.idempotency_key}"' in core


def test_invoice_delivery_failures_are_recorded_and_retried_per_invoice() -> None:
    core = backend("app/services/mollie_billing_core.py")

    assert "def _record_invoice_delivery_failure(" in core
    assert '"delivery_attempts"' in core
    assert '"last_delivery_error"' in core
    assert "await _record_invoice_delivery_failure(invoice_id, exc)" in core
    assert "continue" in core[core.index("async def _sync_receipts"):]


def test_authenticated_invoice_pdf_endpoint_is_available_for_owned_invoices() -> None:
    route = backend("app/api/routes/billing.py")
    pdf = backend("app/services/billing_invoice_pdf.py")

    assert '@router.get("/invoices/{invoice_id}/pdf")' in route
    assert "BillingInvoice.organization_id == user.organization_id" in route
    assert 'media_type="application/pdf"' in route
    assert "def build_billing_invoice_pdf(" in pdf
