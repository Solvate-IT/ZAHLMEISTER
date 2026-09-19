from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.billing import BillingInvoice
from app.services.billing_invoice_copy import billing_invoice_copy


_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_FONT_REGULAR = _FONT_DIR / "DejaVuSans.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSans-Bold.ttf"
_FONT_NAME = "DejaVuSans"
_FONT_BOLD_NAME = "DejaVuSans-Bold"

if _FONT_REGULAR.is_file() and _FONT_BOLD.is_file():
    pdfmetrics.registerFont(TTFont(_FONT_NAME, str(_FONT_REGULAR)))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD_NAME, str(_FONT_BOLD)))
else:
    _FONT_NAME = "Helvetica"
    _FONT_BOLD_NAME = "Helvetica-Bold"


_LABELS = {
    "de": {
        "title": "Rechnung",
        "invoice_number": "Rechnungsnummer",
        "invoice_date": "Rechnungsdatum",
        "seller": "Rechnungssteller",
        "recipient": "Rechnungsempfänger",
        "period": "Leistungszeitraum",
        "description": "Leistung",
        "net": "Netto",
        "vat": "USt.",
        "total": "Gesamt",
        "paid": "Bezahlt",
        "payment_reference": "Zahlungsreferenz",
    },
    "en": {
        "title": "Invoice",
        "invoice_number": "Invoice number",
        "invoice_date": "Invoice date",
        "seller": "Seller",
        "recipient": "Recipient",
        "period": "Billing period",
        "description": "Description",
        "net": "Net",
        "vat": "VAT",
        "total": "Total",
        "paid": "Paid",
        "payment_reference": "Payment reference",
    },
}


def _labels(locale: str) -> dict[str, str]:
    language = (locale or "en").replace("_", "-").split("-", 1)[0].lower()
    return _LABELS.get(language, _LABELS["en"])


def _details(item: BillingInvoice) -> dict[str, Any]:
    try:
        value = json.loads(item.details_json or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _party_lines(party: dict[str, Any]) -> list[str]:
    name = (
        party.get("organizationName")
        or " ".join(
            value
            for value in (party.get("givenName"), party.get("familyName"))
            if isinstance(value, str) and value.strip()
        )
        or party.get("legal_name")
        or ""
    )
    lines = [str(name)] if name else []
    street = party.get("streetAndNumber") or party.get("street_and_number")
    if street:
        lines.append(str(street))
    postal = party.get("postalCode") or party.get("postal_code") or ""
    city = party.get("city") or ""
    locality = " ".join(value for value in (str(postal).strip(), str(city).strip()) if value)
    if locality:
        lines.append(locality)
    region = party.get("region")
    if region:
        lines.append(str(region))
    country = party.get("country")
    if country:
        lines.append(str(country))
    vat = party.get("vatNumber") or party.get("vat_number")
    if vat:
        lines.append(f"VAT: {vat}")
    org = party.get("organizationNumber") or party.get("organization_number")
    if org:
        lines.append(f"Registration: {org}")
    email = party.get("email") or party.get("billing_email")
    if email:
        lines.append(str(email))
    return lines


def _date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%Y")
        except ValueError:
            return value[:10]
    return ""


def _money(value: Decimal | None, currency: str) -> str:
    amount = Decimal(value or 0).quantize(Decimal("0.01"))
    return f"{amount:.2f} {currency}"


def build_billing_invoice_pdf(item: BillingInvoice, locale: str) -> bytes:
    if not item.invoice_number:
        raise ValueError("Invoice number is not available yet")

    labels = _labels(locale)
    details = _details(item)
    recipient = details.get("recipient")
    seller = details.get("seller")
    if not isinstance(recipient, dict):
        raise ValueError("Invoice recipient snapshot is missing")
    if not isinstance(seller, dict):
        seller = {
            "legal_name": item.seller_legal_name,
            "country": item.seller_country,
            "vat_number": item.seller_vat_number,
        }

    issued_at = (
        details.get("provider_issued_at")
        or details.get("provider_created_at")
        or item.paid_at
        or item.created_at
    )
    copy = billing_invoice_copy(locale)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{labels['title']} {item.invoice_number}",
        author=str(seller.get("legal_name") or "Zahlmeister"),
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Title"],
        fontName=_FONT_BOLD_NAME,
        fontSize=20,
        leading=24,
        spaceAfter=12,
    )
    body = ParagraphStyle(
        "InvoiceBody",
        parent=styles["BodyText"],
        fontName=_FONT_NAME,
        fontSize=9.5,
        leading=13,
    )
    body_bold = ParagraphStyle(
        "InvoiceBodyBold",
        parent=body,
        fontName=_FONT_BOLD_NAME,
    )
    right = ParagraphStyle(
        "InvoiceRight",
        parent=body,
        alignment=TA_RIGHT,
    )

    story = [
        Paragraph(labels["title"], title_style),
        Table(
            [
                [Paragraph(labels["invoice_number"], body), Paragraph(str(item.invoice_number), right)],
                [Paragraph(labels["invoice_date"], body), Paragraph(_date(issued_at), right)],
                [
                    Paragraph(labels["period"], body),
                    Paragraph(f"{_date(item.period_start)} - {_date(item.period_end)}", right),
                ],
            ],
            colWidths=[55 * mm, 101 * mm],
        ),
        Spacer(1, 9 * mm),
    ]

    seller_text = "<br/>".join(_party_lines(seller))
    recipient_text = "<br/>".join(_party_lines(recipient))
    parties = Table(
        [
            [Paragraph(labels["seller"], body_bold), Paragraph(labels["recipient"], body_bold)],
            [Paragraph(seller_text, body), Paragraph(recipient_text, body)],
        ],
        colWidths=[78 * mm, 78 * mm],
    )
    parties.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                ("RIGHTPADDING", (0, 0), (0, -1), 10),
            ]
        )
    )
    story.extend([parties, Spacer(1, 10 * mm)])

    net = Decimal(item.net_amount or 0)
    tax = Decimal(item.tax_amount or 0)
    gross = Decimal(item.gross_amount)
    line_table = Table(
        [
            [
                Paragraph(labels["description"], body_bold),
                Paragraph(labels["net"], right),
                Paragraph(labels["vat"], right),
                Paragraph(labels["total"], right),
            ],
            [
                Paragraph(copy.line_description, body),
                Paragraph(_money(net, item.currency), right),
                Paragraph(f"{Decimal(item.vat_rate):.2f} %<br/>{_money(tax, item.currency)}", right),
                Paragraph(_money(gross, item.currency), right),
            ],
        ],
        colWidths=[75 * mm, 27 * mm, 27 * mm, 27 * mm],
        repeatRows=1,
    )
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D5DD")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E4E7EC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([line_table, Spacer(1, 7 * mm)])

    totals = Table(
        [
            [Paragraph(labels["net"], body), Paragraph(_money(net, item.currency), right)],
            [Paragraph(labels["vat"], body), Paragraph(_money(tax, item.currency), right)],
            [Paragraph(labels["total"], body_bold), Paragraph(_money(gross, item.currency), ParagraphStyle("InvoiceTotal", parent=right, fontName=_FONT_BOLD_NAME))],
        ],
        colWidths=[42 * mm, 38 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.extend([totals, Spacer(1, 8 * mm)])

    if item.tax_treatment == "eu_reverse_charge":
        story.extend([Paragraph(copy.reverse_charge_memo, body), Spacer(1, 4 * mm)])
    if item.paid_at:
        story.append(Paragraph(f"{labels['paid']}: {_date(item.paid_at)}", body_bold))
    if item.payment_reference:
        story.append(Paragraph(f"{labels['payment_reference']}: {item.payment_reference}", body))

    doc.build(story)
    return buffer.getvalue()
