from datetime import UTC, datetime
from decimal import Decimal

from app.services.bank_imports import (
    MatchTarget,
    ParsedBankTransaction,
    decide_match,
    parse_camt053,
    parse_csv_statement,
    parse_mt940,
)


def test_csv_parses_localized_amount() -> None:
    rows = parse_csv_statement(
        "Datum;Betrag;Währung;Auftraggeber;Verwendungszweck\n06.09.2026;12,00;EUR;Anna Muster;ZM-ABC123\n".encode()
    )
    assert len(rows) == 1
    assert rows[0].amount == Decimal("12.00")
    assert rows[0].counterparty_name == "Anna Muster"


def test_mt940_parses_incoming_transaction() -> None:
    text = ":20:START\n:60F:C260906EUR0,00\n:61:260906C12,00NTRFNONREF//BANK1\n:86:?20ZM-ABC123?32Anna Muster\n"
    rows = parse_mt940(text)
    assert len(rows) == 1
    assert rows[0].amount == Decimal("12.00")
    assert rows[0].counterparty_name == "Anna Muster"


def test_camt_parses_credit() -> None:
    xml = b'''<?xml version="1.0"?><Document><BkToCstmrStmt><Stmt><Ntry><Amt Ccy="EUR">12.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-09-06</Dt></BookgDt><NtryRef>BANK1</NtryRef><NtryDtls><TxDtls><RltdPties><Dbtr><Nm>Anna Muster</Nm></Dbtr></RltdPties><RmtInf><Ustrd>ZM-ABC123</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>'''
    rows = parse_camt053(xml)
    assert len(rows) == 1
    assert rows[0].currency == "EUR"
    assert rows[0].reference and "ZM-ABC123" in rows[0].reference


def _target(cp_id: str, name: str, reference: str, amount: str = "12.00") -> MatchTarget:
    return MatchTarget(cp_id, "Ausflug", name, reference, Decimal(amount), "EUR")


def test_exact_reference_is_auto_match() -> None:
    tx = ParsedBankTransaction(
        datetime(2026, 9, 6, tzinfo=UTC), Decimal("12.00"), "EUR", "Someone", "Payment ZM-ABC123"
    )
    decision = decide_match(tx, [_target("1", "Anna Muster", "ZM-ABC123")])
    assert decision.status == "auto_matched"
    assert decision.candidate_collection_participant_id == "1"


def test_amount_and_name_requires_review() -> None:
    tx = ParsedBankTransaction(
        datetime(2026, 9, 6, tzinfo=UTC), Decimal("12.00"), "EUR", "Anna Muster", "Ausflug"
    )
    decision = decide_match(tx, [_target("1", "Anna Muster", "ZM-ABC123")])
    assert decision.status == "needs_review"
    assert decision.reason == "amount_and_name"
