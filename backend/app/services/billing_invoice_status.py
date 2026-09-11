from __future__ import annotations


PAID_RECEIPT_TRANSIENT_STATUSES = {"creating", "issuing", "pending-payment"}


def effective_invoice_status(invoice_status: str, payment_status: str | None) -> str:
    """Return the customer-facing status for an invoice backed by a verified payment.

    Billing invoices are created only after the linked Mollie payment has been
    verified as paid. Mollie's Sales Invoice API can nevertheless expose a short
    intermediate state while the paid receipt is being finalized. Do not present
    that provider-side transition as an outstanding customer payment.
    """
    if payment_status == "paid" and invoice_status in PAID_RECEIPT_TRANSIENT_STATUSES:
        return "paid"
    return invoice_status
