from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


@dataclass(slots=True)
class ParsedBankTransaction:
    booked_at: datetime
    amount: Decimal
    currency: str
    counterparty_name: str | None = None
    reference: str | None = None
    bank_transaction_id: str | None = None
    raw_details: str | None = None

    @property
    def fingerprint(self) -> str:
        parts = [
            self.booked_at.date().isoformat(),
            f"{self.amount:.2f}",
            self.currency.upper(),
            normalize_match_text(self.counterparty_name or ""),
            normalize_match_text(self.reference or ""),
        ]
        if self.bank_transaction_id:
            parts.insert(0, normalize_match_text(self.bank_transaction_id))
        key = "|".join(parts)
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class MatchTarget:
    collection_participant_id: str
    collection_name: str
    participant_name: str
    payment_reference: str
    amount: Decimal
    currency: str


@dataclass(slots=True)
class MatchDecision:
    status: str
    candidate_collection_participant_id: str | None
    confidence: Decimal | None
    reason: str | None
    suggestions: list[MatchTarget]


def normalize_match_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    asciiish = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", asciiish.upper()).strip()


def compact_reference(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_match_text(value))


def detect_statement_format(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    stripped = content.lstrip()
    if suffix in {".xml", ".camt"} or stripped.startswith(b"<?xml") or stripped.startswith(b"<Document"):
        return "camt053"
    if suffix in {".sta", ".mt940", ".940"} or b":61:" in content[:10000]:
        return "mt940"
    if suffix in {".csv", ".txt", ".tsv"}:
        return "csv"
    raise ValueError("Unsupported bank statement format. Use CAMT.053, MT940 or CSV.")


def parse_statement(filename: str, content: bytes, default_currency: str = "EUR") -> tuple[str, list[ParsedBankTransaction]]:
    statement_format = detect_statement_format(filename, content)
    if statement_format == "camt053":
        rows = parse_camt053(content)
    elif statement_format == "mt940":
        rows = parse_mt940(content.decode("utf-8", errors="replace"), default_currency)
    else:
        rows = parse_csv_statement(content, default_currency)
    incoming = [row for row in rows if row.amount > 0]
    if not incoming:
        raise ValueError("No incoming transactions found in the bank statement.")
    return statement_format, incoming


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _desc_text(element: ET.Element, names: set[str]) -> list[str]:
    values: list[str] = []
    for child in element.iter():
        if _local_name(child.tag) in names and child.text and child.text.strip():
            values.append(child.text.strip())
    return values


def _first_desc(element: ET.Element, names: set[str]) -> str | None:
    values = _desc_text(element, names)
    return values[0] if values else None


def _parse_iso_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    raw = value.strip()
    try:
        if "T" in raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        parsed_date = date.fromisoformat(raw[:10])
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)


def parse_camt053(content: bytes) -> list[ParsedBankTransaction]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("The CAMT XML file is invalid.") from exc

    rows: list[ParsedBankTransaction] = []
    for entry in (node for node in root.iter() if _local_name(node.tag) == "Ntry"):
        direction = (_first_desc(entry, {"CdtDbtInd"}) or "CRDT").upper()
        if direction != "CRDT":
            continue
        amount_node = next((node for node in entry.iter() if _local_name(node.tag) == "Amt"), None)
        if amount_node is None or not amount_node.text:
            continue
        try:
            amount = Decimal(amount_node.text.strip())
        except InvalidOperation:
            continue
        currency = (amount_node.attrib.get("Ccy") or "EUR").upper()
        booking_date = _first_desc(entry, {"BookgDt", "Dt", "DtTm"})
        # Prefer a date value under BookgDt when nested.
        for child in entry.iter():
            if _local_name(child.tag) == "BookgDt":
                booking_date = _first_desc(child, {"Dt", "DtTm"}) or booking_date
                break
        names = _desc_text(entry, {"Nm"})
        counterparty = names[-1] if names else None
        remittance = _desc_text(entry, {"Ustrd", "AddtlNtryInf", "AddtlTxInf"})
        identifiers = _desc_text(entry, {"EndToEndId", "AcctSvcrRef", "NtryRef", "TxId"})
        reference_parts = []
        for value in [*identifiers, *remittance]:
            if value not in reference_parts:
                reference_parts.append(value)
        bank_id = _first_desc(entry, {"AcctSvcrRef", "NtryRef", "TxId"})
        raw = " | ".join(_desc_text(entry, {"Ustrd", "AddtlNtryInf", "EndToEndId", "AcctSvcrRef", "NtryRef"}))
        rows.append(
            ParsedBankTransaction(
                booked_at=_parse_iso_date(booking_date),
                amount=amount,
                currency=currency,
                counterparty_name=counterparty,
                reference=" | ".join(reference_parts) or None,
                bank_transaction_id=bank_id,
                raw_details=raw or None,
            )
        )
    return rows


_MT940_61_RE = re.compile(
    r"^(?P<date>\d{6})(?P<entry>\d{4})?(?P<dc>R?[CD])(?P<funds>[A-Z])?(?P<amount>[0-9,\.]+)(?P<rest>.*)$"
)


def parse_mt940(content: str, default_currency: str = "EUR") -> list[ParsedBankTransaction]:
    lines = [line.strip("\r") for line in content.splitlines()]
    rows: list[ParsedBankTransaction] = []
    current: ParsedBankTransaction | None = None
    currency = default_currency.upper()

    for line in lines:
        if line.startswith(":60") and len(line) >= 11:
            # Some MT940 exports expose account currency after the opening balance amount.
            match = re.search(r"[CD]\d{6}([A-Z]{3})", line)
            if match:
                currency = match.group(1)
        elif line.startswith(":61:"):
            raw = line[4:]
            match = _MT940_61_RE.match(raw)
            if not match:
                current = None
                continue
            dc = match.group("dc")
            if dc in {"D", "RC"}:
                current = None
                continue
            yy = int(match.group("date")[:2])
            year = 2000 + yy if yy < 70 else 1900 + yy
            month = int(match.group("date")[2:4])
            day = int(match.group("date")[4:6])
            amount = Decimal(match.group("amount").replace(".", "").replace(",", "."))
            rest = match.group("rest").strip()
            bank_id = None
            if "//" in rest:
                bank_id = rest.split("//", 1)[1].strip() or None
            current = ParsedBankTransaction(
                booked_at=datetime(year, month, day, tzinfo=UTC),
                amount=amount,
                currency=currency,
                reference=rest or None,
                bank_transaction_id=bank_id,
                raw_details=raw,
            )
            rows.append(current)
        elif line.startswith(":86:") and current is not None:
            detail = line[4:].strip()
            current.raw_details = " | ".join(filter(None, [current.raw_details, detail]))
            current.reference = " | ".join(filter(None, [current.reference, detail]))
            # Common structured MT940 tags: ?20 purpose, ?32 counterparty name.
            structured_name = re.search(r"\?32([^?]+)", detail)
            if structured_name:
                current.counterparty_name = structured_name.group(1).strip()
            elif not current.counterparty_name:
                name = re.search(r"(?:NAME|AUFTRAGGEBER|ABSENDER)[: ]+([^?|]+)", detail, re.I)
                if name:
                    current.counterparty_name = name.group(1).strip()
    return rows


_HEADER_ALIASES = {
    "date": {"date", "booking date", "booked at", "buchungstag", "buchungsdatum", "datum", "valuta", "value date"},
    "amount": {"amount", "betrag", "umsatz", "value", "credit", "gutschrift"},
    "currency": {"currency", "wahrung", "waehrung", "ccy"},
    "name": {"name", "counterparty", "counterparty name", "auftraggeber", "absender", "payer", "zahler"},
    "reference": {"reference", "purpose", "verwendungszweck", "buchungstext", "text", "details", "memo"},
    "id": {"transaction id", "transaction_id", "id", "reference id", "bank reference"},
    "debit_credit": {"credit debit", "debit credit", "soll haben", "type", "richtung"},
}


def _canonical_header(value: str) -> str | None:
    normalized = normalize_match_text(value).lower()
    for key, aliases in _HEADER_ALIASES.items():
        if normalized in aliases:
            return key
    return None


def _parse_decimal(value: str) -> Decimal:
    raw = (value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not raw:
        raise InvalidOperation
    raw = re.sub(r"[^0-9,\.\-+]", "", raw)
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    return Decimal(raw)


def _parse_flexible_date(value: str) -> datetime:
    raw = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(raw[:10], fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"Unsupported booking date: {value}") from exc


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def parse_csv_statement(content: bytes, default_currency: str = "EUR") -> list[ParsedBankTransaction]:
    text = _decode_csv(content)
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("The CSV file has no header row.")
    mapping = {header: _canonical_header(header) for header in reader.fieldnames}
    if "date" not in mapping.values() or "amount" not in mapping.values():
        raise ValueError("CSV requires a date and amount column.")

    rows: list[ParsedBankTransaction] = []
    for source in reader:
        canonical: dict[str, str] = {}
        for header, value in source.items():
            key = mapping.get(header)
            if key and value is not None:
                canonical[key] = value.strip()
        try:
            amount = _parse_decimal(canonical.get("amount", ""))
            booked_at = _parse_flexible_date(canonical.get("date", ""))
        except (InvalidOperation, ValueError):
            continue
        direction = normalize_match_text(canonical.get("debit_credit", ""))
        if direction in {"D", "DEBIT", "SOLL", "OUT", "OUTGOING"} and amount > 0:
            amount = -amount
        rows.append(
            ParsedBankTransaction(
                booked_at=booked_at,
                amount=amount,
                currency=(canonical.get("currency") or default_currency).upper()[:3],
                counterparty_name=canonical.get("name") or None,
                reference=canonical.get("reference") or None,
                bank_transaction_id=canonical.get("id") or None,
                raw_details=" | ".join(f"{key}={value}" for key, value in canonical.items() if value),
            )
        )
    return rows


def decide_match(transaction: ParsedBankTransaction, targets: Iterable[MatchTarget]) -> MatchDecision:
    compatible = [
        target
        for target in targets
        if target.currency.upper() == transaction.currency.upper()
        and target.amount == transaction.amount
    ]
    if not compatible:
        return MatchDecision("unmatched", None, None, "no_amount_match", [])

    text = compact_reference(" ".join(filter(None, [transaction.reference, transaction.raw_details])))
    for target in compatible:
        reference = compact_reference(target.payment_reference)
        if reference and reference in text:
            return MatchDecision(
                "auto_matched",
                target.collection_participant_id,
                Decimal("1.0000"),
                "payment_reference",
                [target],
            )

    name_text = normalize_match_text(
        " ".join(filter(None, [transaction.counterparty_name, transaction.reference, transaction.raw_details]))
    )
    name_matches: list[MatchTarget] = []
    for target in compatible:
        participant = normalize_match_text(target.participant_name)
        tokens = [token for token in participant.split() if len(token) >= 3]
        if participant and (participant in name_text or (tokens and all(token in name_text for token in tokens))):
            name_matches.append(target)
    if len(name_matches) == 1:
        return MatchDecision(
            "needs_review",
            name_matches[0].collection_participant_id,
            Decimal("0.8500"),
            "amount_and_name",
            name_matches,
        )

    if len(compatible) == 1:
        return MatchDecision(
            "needs_review",
            compatible[0].collection_participant_id,
            Decimal("0.5500"),
            "unique_amount",
            compatible,
        )

    return MatchDecision("needs_review", None, Decimal("0.3000"), "multiple_amount_matches", compatible[:20])
