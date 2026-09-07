from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.services.reports import CollectionReportData, CollectionReportRow, collection_csv, collection_pdf, collection_xlsx


def _data() -> CollectionReportData:
    return CollectionReportData(
        name="Schulausflug",
        locale="de-AT",
        amount=Decimal("12.00"),
        currency="EUR",
        due_at=None,
        created_at=datetime(2026, 9, 6, tzinfo=UTC),
        rows=[
            CollectionReportRow(
                participant_name="Anna Müller",
                amount=Decimal("12.00"),
                currency="EUR",
                status="paid",
                paid_at=datetime(2026, 9, 6, tzinfo=UTC),
                payment_method="bank_import",
                payment_reference="ZM-ABC",
                reminder_count=0,
            )
        ],
    )


def test_csv_export() -> None:
    data = collection_csv(_data(), detailed=True)
    assert "Teilnehmer" in data.decode("utf-8-sig")
    assert "Anna Müller" in data.decode("utf-8-sig")


def test_xlsx_export() -> None:
    data = collection_xlsx(_data(), detailed=False)
    assert data.startswith(b"PK")


def test_pdf_export() -> None:
    pytest.importorskip("reportlab")
    data = collection_pdf(_data(), detailed=False)
    assert data.startswith(b"%PDF")
