import io

from openpyxl import Workbook

from app.services.imports import parse_import


def test_csv_import_preview() -> None:
    data = (
        b"Name;E-Mail;Telefon\n"
        b"Anna Muster;anna@example.at;+43 660 1234567\n"
        b"Max Beispiel;max@example.at;+43 664 7654321\n"
    )
    preview = parse_import("teilnehmer.csv", "text/csv", data)
    assert preview.source_type == "text"
    assert [row.name for row in preview.participants] == ["Anna Muster", "Max Beispiel"]
    assert preview.participants[0].email == "anna@example.at"


def test_excel_import_joins_first_and_last_name() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Vorname", "Nachname", "E-Mail", "Telefon"])
    sheet.append(["Anna", "Muster", "anna@example.at", "+43 660 1234567"])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()

    preview = parse_import(
        "teilnehmer.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        stream.getvalue(),
    )
    assert len(preview.participants) == 1
    assert preview.participants[0].name == "Anna Muster"
    assert preview.participants[0].phone == "+43 660 1234567"
