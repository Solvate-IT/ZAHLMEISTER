from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_organization, get_session
from app.db.session import SessionLocal
from app.models.entities import (
    BankStatementImport,
    BankTransaction,
    Collection,
    CollectionParticipant,
    Organization,
    Participant,
    Payment,
)
from app.schemas.bank_imports import (
    BankImportListItem,
    BankMatchRequest,
    BankMatchSuggestion,
    BankStatementImportRead,
    BankTransactionRead,
)
from app.services.bank_imports import MatchTarget, decide_match, parse_statement
from app.services.locks import transaction_lock

router = APIRouter(prefix="/bank-imports", tags=["bank-imports"])


async def _open_targets(session: AsyncSession, organization_id: UUID) -> list[MatchTarget]:
    rows = (
        await session.execute(
            select(CollectionParticipant, Collection, Participant)
            .join(Collection, Collection.id == CollectionParticipant.collection_id)
            .join(Participant, Participant.id == CollectionParticipant.participant_id)
            .where(
                Collection.organization_id == organization_id,
                CollectionParticipant.status == "open",
            )
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


async def _apply_payment(
    session: AsyncSession,
    transaction: BankTransaction,
    collection_participant_id: UUID,
) -> Payment:
    cp = await session.get(CollectionParticipant, collection_participant_id, with_for_update=True)
    if cp is None:
        raise HTTPException(status_code=404, detail="Collection participant not found")
    collection = await session.get(Collection, cp.collection_id)
    if collection is None or collection.organization_id != transaction.organization_id:
        raise HTTPException(status_code=404, detail="Collection participant not found")
    if Decimal(collection.amount) != Decimal(transaction.amount) or collection.currency != transaction.currency:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transaction amount or currency does not match the collection",
        )
    if cp.status == "paid":
        raise HTTPException(status_code=409, detail="Participant is already marked as paid")

    payment = Payment(
        collection_participant_id=cp.id,
        amount=transaction.amount,
        currency=transaction.currency,
        method="bank_sync" if transaction.source_provider else "bank_import",
        provider=transaction.source_provider or "bank_statement",
        external_reference=transaction.bank_transaction_id or transaction.fingerprint,
        booked_at=transaction.booked_at,
        details=json.dumps(
            {
                "counterparty_name": transaction.counterparty_name,
                "reference": transaction.reference,
                "bank_transaction_id": transaction.bank_transaction_id,
            },
            ensure_ascii=False,
        ),
    )
    session.add(payment)
    await session.flush()
    cp.status = "paid"
    cp.paid_at = transaction.booked_at
    transaction.status = "matched"
    transaction.candidate_collection_participant_id = cp.id
    transaction.match_confidence = Decimal("1.0000")
    transaction.match_reason = transaction.match_reason or "manual_confirmation"
    transaction.applied_payment_id = payment.id
    return payment


async def _recount(session: AsyncSession, item: BankStatementImport) -> None:
    counts = dict(
        (
            await session.execute(
                select(BankTransaction.status, func.count(BankTransaction.id))
                .where(BankTransaction.import_id == item.id)
                .group_by(BankTransaction.status)
            )
        ).all()
    )
    item.auto_matched_count = int(counts.get("auto_matched", 0) + counts.get("matched", 0))
    item.review_count = int(counts.get("needs_review", 0))
    item.unmatched_count = int(counts.get("unmatched", 0))


async def _read_import(session: AsyncSession, organization_id: UUID, import_id: UUID) -> BankStatementImportRead:
    item = await session.get(BankStatementImport, import_id)
    if item is None or item.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Bank import not found")

    rows = (
        await session.execute(
            select(BankTransaction)
            .where(BankTransaction.import_id == item.id)
            .order_by(BankTransaction.booked_at.desc(), BankTransaction.created_at.desc())
        )
    ).scalars().all()
    targets = await _open_targets(session, organization_id)
    target_by_id = {target.collection_participant_id: target for target in targets}

    transaction_reads: list[BankTransactionRead] = []
    for tx in rows:
        candidate = target_by_id.get(str(tx.candidate_collection_participant_id))
        same_amount = [
            target
            for target in targets
            if target.amount == Decimal(tx.amount) and target.currency == tx.currency
        ][:20]
        suggestions = [
            BankMatchSuggestion(
                collection_participant_id=UUID(target.collection_participant_id),
                collection_name=target.collection_name,
                participant_name=target.participant_name,
                amount=target.amount,
                currency=target.currency,
                payment_reference=target.payment_reference,
            )
            for target in same_amount
        ]
        transaction_reads.append(
            BankTransactionRead(
                id=tx.id,
                booked_at=tx.booked_at,
                amount=tx.amount,
                currency=tx.currency,
                counterparty_name=tx.counterparty_name,
                reference=tx.reference,
                status=tx.status,
                match_confidence=tx.match_confidence,
                match_reason=tx.match_reason,
                candidate_collection_participant_id=tx.candidate_collection_participant_id,
                candidate_collection_name=candidate.collection_name if candidate else None,
                candidate_participant_name=candidate.participant_name if candidate else None,
                suggestions=suggestions,
            )
        )

    return BankStatementImportRead(
        id=item.id,
        filename=item.filename,
        format=item.format,
        created_at=item.created_at,
        transaction_count=item.transaction_count,
        auto_matched_count=item.auto_matched_count,
        review_count=item.review_count,
        unmatched_count=item.unmatched_count,
        duplicate_count=item.duplicate_count,
        transactions=transaction_reads,
    )


@router.get("", response_model=list[BankImportListItem])
async def list_bank_imports(
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> list[BankImportListItem]:
    rows = (
        await session.execute(
            select(BankStatementImport)
            .where(BankStatementImport.organization_id == organization.id)
            .order_by(BankStatementImport.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    return [
        BankImportListItem(
            id=item.id,
            filename=item.filename,
            format=item.format,
            created_at=item.created_at,
            transaction_count=item.transaction_count,
            auto_matched_count=item.auto_matched_count,
            review_count=item.review_count,
            unmatched_count=item.unmatched_count,
            duplicate_count=item.duplicate_count,
        )
        for item in rows
    ]


@router.post("", response_model=BankStatementImportRead, status_code=201)
async def import_bank_statement(
    file: UploadFile = File(...),
    organization: Organization = Depends(get_organization),
) -> BankStatementImportRead:
    content = await file.read(20 * 1024 * 1024 + 1)
    if not content:
        raise HTTPException(status_code=422, detail="Bank statement is empty")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Bank statement is too large")

    try:
        statement_format, parsed = parse_statement(
            file.filename or "statement",
            content,
            organization.currency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async with SessionLocal.begin() as session:
        stored_org = await session.get(Organization, organization.id)
        assert stored_org is not None
        await transaction_lock(session, "bank-ingestion", stored_org.id)
        item = BankStatementImport(
            organization_id=stored_org.id,
            filename=(file.filename or "statement")[:500],
            format=statement_format,
            transaction_count=len(parsed),
        )
        session.add(item)
        await session.flush()
        targets = await _open_targets(session, stored_org.id)
        target_buckets: dict[tuple[Decimal, str], list[MatchTarget]] = {}
        for target in targets:
            target_buckets.setdefault((target.amount, target.currency.upper()), []).append(target)
        fingerprints = [row.fingerprint for row in parsed]
        existing_fingerprints = set(
            (
                await session.execute(
                    select(BankTransaction.fingerprint).where(
                        BankTransaction.organization_id == stored_org.id,
                        BankTransaction.fingerprint.in_(fingerprints),
                    )
                )
            ).scalars().all()
        )
        consumed_targets: set[str] = set()

        for row in parsed:
            if row.fingerprint in existing_fingerprints:
                item.duplicate_count += 1
                continue

            candidates = [
                target
                for target in target_buckets.get((row.amount, row.currency.upper()), [])
                if target.collection_participant_id not in consumed_targets
            ]
            decision = decide_match(row, candidates)
            transaction = BankTransaction(
                organization_id=stored_org.id,
                import_id=item.id,
                booked_at=row.booked_at,
                amount=row.amount,
                currency=row.currency,
                counterparty_name=row.counterparty_name,
                reference=row.reference,
                bank_transaction_id=row.bank_transaction_id,
                fingerprint=row.fingerprint,
                status=decision.status,
                candidate_collection_participant_id=(
                    UUID(decision.candidate_collection_participant_id)
                    if decision.candidate_collection_participant_id
                    else None
                ),
                match_confidence=decision.confidence,
                match_reason=decision.reason,
                raw_details=row.raw_details,
            )
            session.add(transaction)

            if decision.status == "auto_matched" and decision.candidate_collection_participant_id:
                try:
                    await _apply_payment(
                        session,
                        transaction,
                        UUID(decision.candidate_collection_participant_id),
                    )
                    # Preserve the fact that this was a safe automatic match.
                    transaction.status = "auto_matched"
                    transaction.match_reason = "payment_reference"
                    consumed_targets.add(decision.candidate_collection_participant_id)
                except HTTPException:
                    transaction.status = "needs_review"
                    transaction.match_reason = "reference_target_already_paid"

        await _recount(session, item)
        import_id = item.id

    async with SessionLocal() as session:
        return await _read_import(session, organization.id, import_id)


@router.get("/{import_id}", response_model=BankStatementImportRead)
async def get_bank_import(
    import_id: UUID,
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> BankStatementImportRead:
    return await _read_import(session, organization.id, import_id)


@router.post("/{import_id}/transactions/{transaction_id}/match", response_model=BankStatementImportRead)
async def confirm_bank_match(
    import_id: UUID,
    transaction_id: UUID,
    payload: BankMatchRequest,
    organization: Organization = Depends(get_organization),
) -> BankStatementImportRead:
    async with SessionLocal.begin() as session:
        item = await session.get(BankStatementImport, import_id)
        tx = await session.get(BankTransaction, transaction_id, with_for_update=True)
        if item is None or item.organization_id != organization.id or tx is None or tx.import_id != item.id:
            raise HTTPException(status_code=404, detail="Bank transaction not found")
        if tx.applied_payment_id is not None:
            raise HTTPException(status_code=409, detail="Bank transaction is already assigned")
        await _apply_payment(session, tx, payload.collection_participant_id)
        tx.match_reason = "manual_confirmation"
        await _recount(session, item)

    async with SessionLocal() as session:
        return await _read_import(session, organization.id, import_id)


@router.post("/{import_id}/transactions/{transaction_id}/ignore", response_model=BankStatementImportRead)
async def ignore_bank_transaction(
    import_id: UUID,
    transaction_id: UUID,
    organization: Organization = Depends(get_organization),
) -> BankStatementImportRead:
    async with SessionLocal.begin() as session:
        item = await session.get(BankStatementImport, import_id)
        tx = await session.get(BankTransaction, transaction_id, with_for_update=True)
        if item is None or item.organization_id != organization.id or tx is None or tx.import_id != item.id:
            raise HTTPException(status_code=404, detail="Bank transaction not found")
        if tx.applied_payment_id is not None:
            raise HTTPException(status_code=409, detail="Assigned transaction cannot be ignored")
        tx.status = "ignored"
        tx.candidate_collection_participant_id = None
        tx.match_confidence = None
        tx.match_reason = "ignored_by_user"
        await _recount(session, item)

    async with SessionLocal() as session:
        return await _read_import(session, organization.id, import_id)
