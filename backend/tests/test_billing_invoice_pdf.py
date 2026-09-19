import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.models.billing import BillingInvoice
from app.services.billing_invoice_pdf import build_billing_invoice_pdf


def test_invoice_pdf_renders_from_immutable_billing_snapshot() -> None:
    issued = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
    invoice = BillingInvoice(
        id=uuid4(),
        organization_id=uuid4(),
        provider="mollie",
        product_id="zahlmeister.pro.yearly",
        tariff_version="2026-09-17",
        period_start=issued,
        period_end=issued + timedelta(days=365),
        net_amount=Decimal("0.83"),
        tax_amount=Decimal("0.17"),
        gross_amount=Decimal("1.00"),
        currency="EUR",
        vat_rate=Decimal("20.000"),
        vat_scheme="standard",
        tax_treatment="domestic_standard",
        recipient_country="AT",
        recipient_type="consumer",
        seller_legal_name="Solvate IT GmbH",
        seller_country="AT",
        seller_vat_number="ATU77378124",
        invoice_number="INV-0000123",
        status="paid",
        payment_reference="tr_test",
        paid_at=issued,
        created_at=issued,
        details_json=json.dumps(
            {
                "recipient": {
                    "type": "consumer",
                    "givenName": "Max",
                    "familyName": "Mustermann",
                    "email": "max@example.test",
                    "streetAndNumber": "Musterweg 1",
                    "postalCode": "8010",
                    "city": "Graz",
                    "country": "AT",
                },
                "seller": {
                    "legal_name": "Solvate IT GmbH",
                    "billing_email": "Rechnung@Solvate.at",
                    "street_and_number": "Lagergasse 23",
                    "postal_code": "8010",
                    "city": "Graz",
                    "country": "AT",
                    "vat_number": "ATU77378124",
                    "organization_number": "565826y",
                },
                "provider_issued_at": issued.isoformat(),
            }
        ),
    )

    pdf = build_billing_invoice_pdf(invoice, "de")

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_invoice_pdf_requires_provider_invoice_number() -> None:
    invoice = BillingInvoice(invoice_number=None)

    try:
        build_billing_invoice_pdf(invoice, "en")
    except ValueError as exc:
        assert "Invoice number" in str(exc)
    else:
        raise AssertionError("PDF generation must not invent an invoice number")
