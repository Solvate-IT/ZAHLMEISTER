from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font


@dataclass(slots=True)
class CollectionReportRow:
    participant_name: str
    amount: Decimal
    currency: str
    status: str
    paid_at: datetime | None
    payment_method: str | None
    payment_reference: str
    reminder_count: int


@dataclass(slots=True)
class CollectionReportData:
    name: str
    locale: str
    amount: Decimal
    currency: str
    due_at: datetime | None
    created_at: datetime
    rows: list[CollectionReportRow]


_REPORT_LABELS: dict[str, tuple[str, ...]] = {
    "bg": ("Участник", "Сума", "Валута", "Статус", "Платено на", "Начин на плащане", "Референция", "Напомняния", "Платено", "Отворено", "Падеж"),
    "cs": ("Účastník", "Částka", "Měna", "Stav", "Zaplaceno", "Způsob platby", "Reference", "Připomínky", "Zaplaceno", "Otevřeno", "Splatnost"),
    "da": ("Deltager", "Beløb", "Valuta", "Status", "Betalt", "Betalingsmetode", "Reference", "Påmindelser", "Betalt", "Åben", "Forfald"),
    "de": ("Teilnehmer", "Betrag", "Währung", "Status", "Bezahlt am", "Zahlungsart", "Zahlungsreferenz", "Erinnerungen", "Bezahlt", "Offen", "Fälligkeit"),
    "el": ("Συμμετέχων", "Ποσό", "Νόμισμα", "Κατάσταση", "Πληρώθηκε", "Τρόπος πληρωμής", "Αναφορά", "Υπενθυμίσεις", "Πληρωμένο", "Ανοικτό", "Λήξη"),
    "en": ("Participant", "Amount", "Currency", "Status", "Paid at", "Payment method", "Payment reference", "Reminders", "Paid", "Open", "Due"),
    "es": ("Participante", "Importe", "Moneda", "Estado", "Pagado el", "Método de pago", "Referencia", "Recordatorios", "Pagado", "Abierto", "Vencimiento"),
    "et": ("Osaleja", "Summa", "Valuuta", "Olek", "Makstud", "Makseviis", "Makseviide", "Meeldetuletused", "Makstud", "Avatud", "Tähtaeg"),
    "fi": ("Osallistuja", "Summa", "Valuutta", "Tila", "Maksettu", "Maksutapa", "Maksuviite", "Muistutukset", "Maksettu", "Avoin", "Eräpäivä"),
    "fr": ("Participant", "Montant", "Devise", "Statut", "Payé le", "Mode de paiement", "Référence", "Rappels", "Payé", "Ouvert", "Échéance"),
    "ga": ("Rannpháirtí", "Méid", "Airgeadra", "Stádas", "Íoctha", "Modh íocaíochta", "Tagairt", "Meabhrúcháin", "Íoctha", "Oscailte", "Dlite"),
    "hr": ("Sudionik", "Iznos", "Valuta", "Status", "Plaćeno", "Način plaćanja", "Referenca", "Podsjetnici", "Plaćeno", "Otvoreno", "Rok"),
    "hu": ("Résztvevő", "Összeg", "Pénznem", "Állapot", "Fizetve", "Fizetési mód", "Hivatkozás", "Emlékeztetők", "Fizetve", "Nyitott", "Esedékesség"),
    "it": ("Partecipante", "Importo", "Valuta", "Stato", "Pagato il", "Metodo di pagamento", "Riferimento", "Promemoria", "Pagato", "Aperto", "Scadenza"),
    "lt": ("Dalyvis", "Suma", "Valiuta", "Būsena", "Sumokėta", "Mokėjimo būdas", "Nuoroda", "Priminimai", "Sumokėta", "Atvira", "Terminas"),
    "lv": ("Dalībnieks", "Summa", "Valūta", "Statuss", "Samaksāts", "Maksājuma veids", "Atsauce", "Atgādinājumi", "Samaksāts", "Atvērts", "Termiņš"),
    "mt": ("Parteċipant", "Ammont", "Munita", "Status", "Imħallas", "Metodu ta’ ħlas", "Referenza", "Tfakkiriet", "Imħallas", "Miftuħ", "Skadenza"),
    "nl": ("Deelnemer", "Bedrag", "Valuta", "Status", "Betaald op", "Betaalmethode", "Betalingskenmerk", "Herinneringen", "Betaald", "Open", "Vervaldatum"),
    "pl": ("Uczestnik", "Kwota", "Waluta", "Status", "Zapłacono", "Metoda płatności", "Referencja", "Przypomnienia", "Zapłacono", "Otwarte", "Termin"),
    "pt": ("Participante", "Montante", "Moeda", "Estado", "Pago em", "Método de pagamento", "Referência", "Lembretes", "Pago", "Aberto", "Vencimento"),
    "ro": ("Participant", "Sumă", "Monedă", "Stare", "Plătit la", "Metodă de plată", "Referință", "Mementouri", "Plătit", "Deschis", "Scadență"),
    "sk": ("Účastník", "Suma", "Mena", "Stav", "Zaplatené", "Spôsob platby", "Referencia", "Pripomienky", "Zaplatené", "Otvorené", "Splatnosť"),
    "sl": ("Udeleženec", "Znesek", "Valuta", "Status", "Plačano", "Način plačila", "Sklic", "Opomniki", "Plačano", "Odprto", "Rok"),
    "sv": ("Deltagare", "Belopp", "Valuta", "Status", "Betald", "Betalningsmetod", "Betalningsreferens", "Påminnelser", "Betald", "Öppen", "Förfallodatum"),
}

_PAYMENT_METHOD_LABELS: dict[str, dict[str, str]] = {
    "bg": {"manual": "Ръчно", "bank_import": "Банков импорт", "bank_sync": "Банкова синхронизация", "mollie": "Онлайн плащане"},
    "cs": {"manual": "Ručně", "bank_import": "Import banky", "bank_sync": "Bankovní synchronizace", "mollie": "Online platba"},
    "da": {"manual": "Manuel", "bank_import": "Bankimport", "bank_sync": "Banksynkronisering", "mollie": "Onlinebetaling"},
    "de": {"manual": "Manuell", "bank_import": "Bankimport", "bank_sync": "BankSync", "mollie": "Online-Zahlung"},
    "el": {"manual": "Χειροκίνητα", "bank_import": "Εισαγωγή τράπεζας", "bank_sync": "Συγχρονισμός τράπεζας", "mollie": "Online πληρωμή"},
    "en": {"manual": "Manual", "bank_import": "Bank import", "bank_sync": "Bank sync", "mollie": "Online payment"},
    "es": {"manual": "Manual", "bank_import": "Importación bancaria", "bank_sync": "Sincronización bancaria", "mollie": "Pago en línea"},
    "et": {"manual": "Käsitsi", "bank_import": "Pangaimport", "bank_sync": "Pangasünkroniseerimine", "mollie": "Veebimakse"},
    "fi": {"manual": "Manuaalinen", "bank_import": "Pankkituonti", "bank_sync": "Pankkisynkronointi", "mollie": "Verkkomaksu"},
    "fr": {"manual": "Manuel", "bank_import": "Import bancaire", "bank_sync": "Synchronisation bancaire", "mollie": "Paiement en ligne"},
    "ga": {"manual": "Láimhe", "bank_import": "Iompórtáil bainc", "bank_sync": "Sioncronú bainc", "mollie": "Íocaíocht ar líne"},
    "hr": {"manual": "Ručno", "bank_import": "Uvoz banke", "bank_sync": "Sinkronizacija banke", "mollie": "Online plaćanje"},
    "hu": {"manual": "Kézi", "bank_import": "Banki import", "bank_sync": "Bankszinkron", "mollie": "Online fizetés"},
    "it": {"manual": "Manuale", "bank_import": "Importazione bancaria", "bank_sync": "Sincronizzazione bancaria", "mollie": "Pagamento online"},
    "lt": {"manual": "Rankinis", "bank_import": "Banko importas", "bank_sync": "Banko sinchronizavimas", "mollie": "Internetinis mokėjimas"},
    "lv": {"manual": "Manuāli", "bank_import": "Bankas imports", "bank_sync": "Bankas sinhronizācija", "mollie": "Tiešsaistes maksājums"},
    "mt": {"manual": "Manwali", "bank_import": "Import bankarju", "bank_sync": "Sinkronizzazzjoni bankarja", "mollie": "Ħlas online"},
    "nl": {"manual": "Handmatig", "bank_import": "Bankimport", "bank_sync": "Banksynchronisatie", "mollie": "Online betaling"},
    "pl": {"manual": "Ręcznie", "bank_import": "Import bankowy", "bank_sync": "Synchronizacja bankowa", "mollie": "Płatność online"},
    "pt": {"manual": "Manual", "bank_import": "Importação bancária", "bank_sync": "Sincronização bancária", "mollie": "Pagamento online"},
    "ro": {"manual": "Manual", "bank_import": "Import bancar", "bank_sync": "Sincronizare bancară", "mollie": "Plată online"},
    "sk": {"manual": "Ručne", "bank_import": "Import banky", "bank_sync": "Banková synchronizácia", "mollie": "Online platba"},
    "sl": {"manual": "Ročno", "bank_import": "Uvoz banke", "bank_sync": "Bančna sinhronizacija", "mollie": "Spletno plačilo"},
    "sv": {"manual": "Manuell", "bank_import": "Bankimport", "bank_sync": "Banksynkronisering", "mollie": "Onlinebetalning"},
}


def _payment_method(locale: str, method: str | None) -> str:
    if not method:
        return ""
    language = locale.split("-", 1)[0].lower()
    return _PAYMENT_METHOD_LABELS.get(language, _PAYMENT_METHOD_LABELS["en"]).get(method, method)


def _worksheet_title(name: str) -> str:
    invalid = set('[]:*?/\\')
    clean = ''.join('_' if char in invalid else char for char in name).strip() or 'Zahlmeister'
    return clean[:31]



def _labels(locale: str) -> tuple[str, ...]:
    return _REPORT_LABELS.get(locale.split("-", 1)[0].lower(), _REPORT_LABELS["en"])


def _headers(data: CollectionReportData, detailed: bool) -> list[str]:
    labels = _labels(data.locale)
    headers = list(labels[:8])
    return headers if detailed else headers[:4]


def _row_values(row: CollectionReportRow, detailed: bool, locale: str) -> list[str]:
    labels = _labels(locale)
    status = labels[8] if row.status == "paid" else labels[9] if row.status == "open" else row.status
    base = [row.participant_name, f"{row.amount:.2f}", row.currency, status]
    if not detailed:
        return base
    return [
        *base,
        row.paid_at.isoformat(sep=" ", timespec="minutes") if row.paid_at else "",
        _payment_method(locale, row.payment_method),
        row.payment_reference,
        str(row.reminder_count),
    ]


def collection_csv(data: CollectionReportData, detailed: bool = False) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    headers = _headers(data, detailed)
    writer.writerow(headers)
    for row in data.rows:
        writer.writerow(_row_values(row, detailed, data.locale))
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def collection_xlsx(data: CollectionReportData, detailed: bool = False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _worksheet_title(data.name)
    headers = _headers(data, detailed)
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in data.rows:
        sheet.append(_row_values(row, detailed, data.locale))
    for column in sheet.columns:
        width = min(45, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
        sheet.column_dimensions[column[0].column_letter].width = width
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _register_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            if "ZahlmeisterSans" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("ZahlmeisterSans", str(candidate)))
            return "ZahlmeisterSans"
    return "Helvetica"


def collection_pdf(data: CollectionReportData, detailed: bool = False) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = io.BytesIO()
    font_name = _register_font()
    page = landscape(A4) if detailed else A4
    document = SimpleDocTemplate(
        output,
        pagesize=page,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=data.name,
    )
    styles = getSampleStyleSheet()
    for style_name in ("Title", "Normal"):
        styles[style_name].fontName = font_name
    story = [Paragraph(data.name, styles["Title"])]
    paid = sum(1 for row in data.rows if row.status == "paid")
    total = len(data.rows)
    labels = _labels(data.locale)
    story.append(Paragraph(f"{labels[8]}: {paid}/{total}", styles["Normal"]))
    if data.due_at:
        story.append(Paragraph(f"{labels[10]}: {data.due_at.date().isoformat()}", styles["Normal"]))
    story.append(Spacer(1, 8))

    headers = _headers(data, detailed)
    table_data = [headers] + [_row_values(row, detailed, data.locale) for row in data.rows]
    table = Table(table_data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    document.build(story)
    return output.getvalue()
