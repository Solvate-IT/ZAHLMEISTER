from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    BankSyncAccount,
    BankSyncConnection,
    BankStatementImport,
    BankTransaction,
    Collection,
    CollectionParticipant,
    Organization,
    Participant,
    Payment,
)
from app.services.bank_imports import MatchTarget, ParsedBankTransaction, decide_match
from app.services.bank_sync_providers import get_bank_sync_provider
from app.services.locks import transaction_lock


def _attr(attributes: dict, *names: str):
    for name in names:
        value = attributes.get(name)
        if value not in (None, ""):
            return value
    return None


def parse_ponto_account(item: dict) -> dict:
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    return {
        "external_id": str(item.get("id") or ""),
        "name": str(_attr(attrs, "description", "name", "product", "reference") or "") or None,
        "iban": str(_attr(attrs, "reference", "iban", "accountReference") or "") or None,
        "currency": str(_attr(attrs, "currency", "currencyCode") or "")[:3].upper() or None,
    }


def _parse_datetime(value) -> datetime:
    if not value:
        return datetime.now(UTC)
    raw = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_ponto_transaction(item: dict, default_currency: str | None = None) -> ParsedBankTransaction | None:
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    try:
        amount = Decimal(str(_attr(attrs, "amount") or "0"))
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    currency = str(_attr(attrs, "currency") or default_currency or "EUR").upper()[:3]
    reference_parts = [
        _attr(attrs, "remittanceInformation", "remittance_information"),
        _attr(attrs, "additionalInformation", "additional_information"),
        _attr(attrs, "endToEndId", "end_to_end_id"),
        _attr(attrs, "internalReference", "internal_reference"),
    ]
    reference = " | ".join(str(v) for v in reference_parts if v) or None
    transaction_id = str(item.get("id") or _attr(attrs, "internalReference", "internal_reference") or "") or None
    return ParsedBankTransaction(
        booked_at=_parse_datetime(_attr(attrs, "executionDate", "execution_date", "valueDate", "value_date", "createdAt", "created_at")),
        amount=amount,
        currency=currency,
        counterparty_name=str(_attr(attrs, "counterpartName", "counterpart_name", "counterpartyName") or "") or None,
        reference=reference,
        bank_transaction_id=transaction_id,
        raw_details=json.dumps(attrs, ensure_ascii=False, separators=(",", ":")),
    )


async def _targets(session: AsyncSession, organization_id: UUID) -> list[MatchTarget]:
    rows = (
        await session.execute(
            select(CollectionParticipant, Collection, Participant)
            .join(Collection, Collection.id == CollectionParticipant.collection_id)
            .join(Participant, Participant.id == CollectionParticipant.participant_id)
            .where(Collection.organization_id == organization_id, CollectionParticipant.status == "open")
        )
    ).all()
    return [
        MatchTarget(
            collection_participant_id=str(cp.id),
            collection_name=collection.name,
            participant_name=participant.name,
            payment_reference=cp.payment_reference,
            amount=Decimal(collection.amount),
            currency=collection.currency,
        )
        for cp, collection, participant in rows
    ]


async def _apply_auto_payment(session: AsyncSession, tx: BankTransaction, cp_id: UUID) -> bool:
    cp = await session.get(CollectionParticipant, cp_id, with_for_update=True)
    if cp is None or cp.status == "paid":
        return False
    collection = await session.get(Collection, cp.collection_id)
    if collection is None or Decimal(collection.amount) != Decimal(tx.amount) or collection.currency != tx.currency:
        return False
    payment = Payment(
        collection_participant_id=cp.id,
        amount=tx.amount,
        currency=tx.currency,
        method="bank_sync",
        provider=tx.source_provider or "bank_sync",
        external_reference=tx.bank_transaction_id or tx.fingerprint,
        booked_at=tx.booked_at,
        details=json.dumps(
            {"counterparty_name": tx.counterparty_name, "reference": tx.reference},
            ensure_ascii=False,
        ),
    )
    session.add(payment)
    await session.flush()
    cp.status = "paid"
    cp.paid_at = tx.booked_at
    tx.status = "matched"
    tx.applied_payment_id = payment.id
    tx.candidate_collection_participant_id = cp.id
    tx.match_confidence = Decimal("1.0000")
    tx.match_reason = "payment_reference"
    return True


async def refresh_accounts(session: AsyncSession, connection: BankSyncConnection) -> list[BankSyncAccount]:
    provider = get_bank_sync_provider(connection.provider)
    remote = await provider.list_accounts(connection)
    existing = {
        row.external_id: row
        for row in (
            await session.execute(
                select(BankSyncAccount).where(BankSyncAccount.connection_id == connection.id)
            )
        ).scalars().all()
    }
    result: list[BankSyncAccount] = []
    remote_ids: set[str] = set()
    for item in remote:
        parsed = parse_ponto_account(item)
        external_id = parsed["external_id"]
        if not external_id:
            continue
        remote_ids.add(external_id)
        account = existing.get(external_id)
        if account is None:
            account = BankSyncAccount(
                organization_id=connection.organization_id,
                connection_id=connection.id,
                external_id=external_id,
            )
            session.add(account)
        account.name = parsed["name"]
        account.iban = parsed["iban"]
        account.currency = parsed["currency"]
        result.append(account)

    # Ponto's account list is authoritative for the current integration. Remove
    # accounts that were revoked in Ponto; historical transactions remain intact
    # because their bank_sync_account_id uses ON DELETE SET NULL.
    for external_id, account in existing.items():
        if external_id not in remote_ids:
            await session.delete(account)

    await session.flush()
    return result


async def sync_connection(session: AsyncSession, connection: BankSyncConnection) -> dict[str, int | datetime]:
    organization = await session.get(Organization, connection.organization_id)
    if organization is None:
        raise ValueError("BankSync organization not found")
    await transaction_lock(session, "bank-ingestion", organization.id)
    accounts = await refresh_accounts(session, connection)
    targets = await _targets(session, connection.organization_id)
    imported = auto_matched = needs_review = duplicates = 0
    now = datetime.now(UTC)

    # With no open collection there is nothing useful to match, so do not pull and
    # persist unrelated account history. For active collections, ignore transactions
    # that clearly predate the oldest open collection.
    oldest_open_collection = await session.scalar(
        select(func.min(Collection.created_at))
        .join(CollectionParticipant, CollectionParticipant.collection_id == Collection.id)
        .where(
            Collection.organization_id == connection.organization_id,
            CollectionParticipant.status == "open",
        )
    )
    relevant_since = (oldest_open_collection - timedelta(days=7)) if oldest_open_collection else None
    sync_import: BankStatementImport | None = None
    consumed_targets: set[str] = set()

    if not targets:
        for account in accounts:
            account.last_sync_at = now
        connection.last_sync_at = now
        connection.last_error = None
        connection.status = "connected"
        return {
            "imported": 0,
            "auto_matched": 0,
            "needs_review": 0,
            "duplicates": 0,
            "synced_at": now,
        }

    for account in accounts:
        if not account.enabled:
            continue
        provider = get_bank_sync_provider(connection.provider)
        for item in await provider.list_transactions(connection, account.external_id):
            parsed = parse_ponto_transaction(item, account.currency)
            if parsed is None:
                continue
            if relevant_since is not None and parsed.booked_at < relevant_since:
                continue
            duplicate = await session.scalar(
                select(BankTransaction.id).where(
                    BankTransaction.organization_id == connection.organization_id,
                    BankTransaction.fingerprint == parsed.fingerprint,
                )
            )
            if duplicate is not None:
                duplicates += 1
                continue

            # BankSync runs are represented as normal bank imports as well. This keeps
            # uncertain matches in the same quiet review workflow as uploaded statements.
            if sync_import is None:
                sync_import = BankStatementImport(
                    organization_id=connection.organization_id,
                    filename=f"Ponto BankSync {now.date().isoformat()}",
                    format="ponto",
                )
                session.add(sync_import)
                await session.flush()

            candidates = [
                target for target in targets
                if target.collection_participant_id not in consumed_targets
            ]
            decision = decide_match(parsed, candidates)
            tx = BankTransaction(
                organization_id=connection.organization_id,
                import_id=sync_import.id,
                bank_sync_account_id=account.id,
                source_provider=connection.provider,
                booked_at=parsed.booked_at,
                amount=parsed.amount,
                currency=parsed.currency,
                counterparty_name=parsed.counterparty_name,
                reference=parsed.reference,
                bank_transaction_id=parsed.bank_transaction_id,
                fingerprint=parsed.fingerprint,
                status=decision.status,
                candidate_collection_participant_id=(
                    UUID(decision.candidate_collection_participant_id)
                    if decision.candidate_collection_participant_id
                    else None
                ),
                match_confidence=decision.confidence,
                match_reason=decision.reason,
                raw_details=parsed.raw_details,
            )
            session.add(tx)
            await session.flush()
            imported += 1
            if decision.status == "auto_matched" and decision.candidate_collection_participant_id:
                applied = await _apply_auto_payment(
                    session, tx, UUID(decision.candidate_collection_participant_id)
                )
                if applied:
                    # Keep the review/export counters consistent with uploaded statements.
                    tx.status = "auto_matched"
                    tx.match_reason = "payment_reference"
                    consumed_targets.add(decision.candidate_collection_participant_id)
                    auto_matched += 1
                else:
                    tx.status = "needs_review"
                    tx.match_reason = "reference_target_already_paid"
                    needs_review += 1
            elif decision.status == "needs_review":
                needs_review += 1
        account.last_sync_at = now

    if sync_import is not None:
        sync_import.transaction_count = imported
        sync_import.auto_matched_count = auto_matched
        sync_import.review_count = needs_review
        sync_import.unmatched_count = max(0, imported - auto_matched - needs_review)
        sync_import.duplicate_count = duplicates

    connection.last_sync_at = now
    connection.last_error = None
    connection.status = "connected"
    return {
        "imported": imported,
        "auto_matched": auto_matched,
        "needs_review": needs_review,
        "duplicates": duplicates,
        "synced_at": now,
    }
