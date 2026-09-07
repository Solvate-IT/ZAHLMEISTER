import csv
import io
import json
import zipfile
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_auth_session, get_current_user, get_session
from app.db.session import SessionLocal
from app.models.entities import (
    AuthSession,
    BankStatementImport,
    BankSyncAccount,
    BankSyncConnection,
    BankTransaction,
    Collection,
    CollectionParticipant,
    CommunicationMessage,
    OnlinePaymentAttempt,
    OnlinePaymentConnection,
    Organization,
    Participant,
    ParticipantList,
    Payment,
    User,
)
from app.schemas.account import ChangePasswordRequest, DeleteAccountRequest, ProfileUpdateRequest
from app.schemas.auth import UserRead
from app.services.account import invalidate_user_sessions
from app.services.auth import hash_password, verify_password

router = APIRouter(prefix="/account", tags=["account"])


def _user_read(user: User, organization: Organization) -> UserRead:
    return UserRead(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        organization_id=str(user.organization_id),
        organization_name=organization.name,
        locale=organization.locale,
        currency=organization.currency,
        email_verified=user.email_verified_at is not None,
    )


@router.patch("/profile", response_model=UserRead)
async def update_profile(
    payload: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
) -> UserRead:
    async with SessionLocal.begin() as session:
        stored = await session.get(User, user.id)
        if stored is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
        organization = await session.get(Organization, stored.organization_id)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        if payload.display_name is not None:
            stored.display_name = payload.display_name
        if payload.organization_name is not None:
            organization.name = payload.organization_name
        if payload.locale is not None:
            organization.locale = payload.locale
        if payload.currency is not None:
            organization.currency = payload.currency
        await session.flush()
        return _user_read(stored, organization)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    auth_session: AuthSession = Depends(get_current_auth_session),
) -> None:
    async with SessionLocal.begin() as session:
        stored = await session.get(User, user.id)
        if stored is None or not verify_password(stored.password_hash, payload.current_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
        stored.password_hash = hash_password(payload.new_password)
        await invalidate_user_sessions(session, stored.id, keep_session_id=auth_session.id)


def _csv_bytes(rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    if not rows:
        return b""
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


async def _export_rows(session: AsyncSession, organization_id):
    lists = list((await session.scalars(select(ParticipantList).where(ParticipantList.organization_id == organization_id))).all())
    list_ids = [item.id for item in lists]
    participants = list((await session.scalars(select(Participant).where(Participant.list_id.in_(list_ids)))).all()) if list_ids else []
    collections = list((await session.scalars(select(Collection).where(Collection.organization_id == organization_id))).all())
    collection_ids = [item.id for item in collections]
    cps = list((await session.scalars(select(CollectionParticipant).where(CollectionParticipant.collection_id.in_(collection_ids)))).all()) if collection_ids else []
    cp_ids = [item.id for item in cps]
    payments = list((await session.scalars(select(Payment).where(Payment.collection_participant_id.in_(cp_ids)))).all()) if cp_ids else []
    messages = list((await session.scalars(select(CommunicationMessage).where(CommunicationMessage.organization_id == organization_id))).all())
    imports = list((await session.scalars(select(BankStatementImport).where(BankStatementImport.organization_id == organization_id))).all())
    transactions = list((await session.scalars(select(BankTransaction).where(BankTransaction.organization_id == organization_id))).all())
    bank_sync_connections = list((await session.scalars(select(BankSyncConnection).where(BankSyncConnection.organization_id == organization_id))).all())
    bank_sync_accounts = list((await session.scalars(select(BankSyncAccount).where(BankSyncAccount.organization_id == organization_id))).all())
    online_payment_connections = list((await session.scalars(select(OnlinePaymentConnection).where(OnlinePaymentConnection.organization_id == organization_id))).all())
    online_payment_attempts = list((await session.scalars(select(OnlinePaymentAttempt).where(OnlinePaymentAttempt.organization_id == organization_id))).all())
    return lists, participants, collections, cps, payments, messages, imports, transactions, bank_sync_connections, bank_sync_accounts, online_payment_connections, online_payment_attempts


def _dt(value) -> str:
    return value.isoformat() if value else ""


@router.get("/export")
async def export_account_data(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    organization = await session.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    (
        lists, participants, collections, cps, payments, messages, imports, transactions,
        bank_sync_connections, bank_sync_accounts, online_payment_connections, online_payment_attempts,
    ) = await _export_rows(session, user.organization_id)

    profile = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "email_verified_at": _dt(user.email_verified_at),
        },
        "organization": {
            "id": str(organization.id),
            "name": organization.name,
            "locale": organization.locale,
            "currency": organization.currency,
            "bank_account_name": organization.bank_account_name,
            "bank_iban": organization.bank_iban,
            "bank_bic": organization.bank_bic,
            "message_include_payment_link": organization.message_include_payment_link,
            "message_include_payment_qr": organization.message_include_payment_qr,
        },
    }

    files: dict[str, bytes] = {
        "profile.json": json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8"),
        "participant_lists.csv": _csv_bytes([
            {"id": str(x.id), "name": x.name, "created_at": _dt(x.created_at)} for x in lists
        ]),
        "participants.csv": _csv_bytes([
            {"id": str(x.id), "list_id": str(x.list_id), "name": x.name, "email": x.email or "", "phone": x.phone or "", "created_at": _dt(x.created_at)} for x in participants
        ]),
        "collections.csv": _csv_bytes([
            {"id": str(x.id), "name": x.name, "participant_list_id": str(x.participant_list_id), "amount": str(x.amount), "currency": x.currency, "status": x.status, "send_at": _dt(x.send_at), "due_at": _dt(x.due_at), "message_include_payment_link": x.message_include_payment_link, "message_include_payment_qr": x.message_include_payment_qr, "created_at": _dt(x.created_at)} for x in collections
        ]),
        "collection_participants.csv": _csv_bytes([
            {"id": str(x.id), "collection_id": str(x.collection_id), "participant_id": str(x.participant_id), "payment_reference": x.payment_reference, "status": x.status, "paid_at": _dt(x.paid_at), "initial_sent_at": _dt(x.initial_sent_at), "reminder_count": x.reminder_count} for x in cps
        ]),
        "payments.csv": _csv_bytes([
            {"id": str(x.id), "collection_participant_id": str(x.collection_participant_id), "amount": str(x.amount), "currency": x.currency, "method": x.method, "provider": x.provider or "", "external_reference": x.external_reference or "", "booked_at": _dt(x.booked_at)} for x in payments
        ]),
        "communications.csv": _csv_bytes([
            {"id": str(x.id), "collection_id": str(x.collection_id), "collection_participant_id": str(x.collection_participant_id), "channel": x.channel, "direction": x.direction, "status": x.status, "sender": x.sender or "", "recipient": x.recipient or "", "subject": x.subject or "", "body": x.body or "", "sent_at": _dt(x.sent_at), "received_at": _dt(x.received_at)} for x in messages
        ]),
        "bank_imports.csv": _csv_bytes([
            {"id": str(x.id), "filename": x.filename, "format": x.format, "transaction_count": x.transaction_count, "created_at": _dt(x.created_at)} for x in imports
        ]),
        "bank_transactions.csv": _csv_bytes([
            {"id": str(x.id), "booked_at": _dt(x.booked_at), "amount": str(x.amount), "currency": x.currency, "counterparty_name": x.counterparty_name or "", "reference": x.reference or "", "status": x.status} for x in transactions
        ]),
        "bank_sync_connections.csv": _csv_bytes([
            {"id": str(x.id), "provider": x.provider, "status": x.status, "account_label": x.account_label or "", "connected_at": _dt(x.connected_at), "last_sync_at": _dt(x.last_sync_at), "last_tested_at": _dt(x.last_tested_at)} for x in bank_sync_connections
        ]),
        "bank_sync_accounts.csv": _csv_bytes([
            {"id": str(x.id), "connection_id": str(x.connection_id), "name": x.name or "", "iban": x.iban or "", "currency": x.currency or "", "enabled": x.enabled, "last_sync_at": _dt(x.last_sync_at)} for x in bank_sync_accounts
        ]),
        "online_payment_connections.csv": _csv_bytes([
            {"id": str(x.id), "provider": x.provider, "status": x.status, "enabled": x.enabled, "account_label": x.account_label or "", "profile_id": x.profile_id or "", "connected_at": _dt(x.connected_at), "last_tested_at": _dt(x.last_tested_at)} for x in online_payment_connections
        ]),
        "online_payment_attempts.csv": _csv_bytes([
            {"id": str(x.id), "collection_participant_id": str(x.collection_participant_id), "provider": x.provider, "external_id": x.external_id or "", "status": x.status, "amount": str(x.amount), "currency": x.currency, "payment_method": x.payment_method or "", "paid_at": _dt(x.paid_at), "created_at": _dt(x.created_at)} for x in online_payment_attempts
        ]),
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="zahlmeister-data-{stamp}.zip"'},
    )


@router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    payload: DeleteAccountRequest,
    user: User = Depends(get_current_user),
) -> None:
    async with SessionLocal.begin() as session:
        stored = await session.get(User, user.id)
        if stored is None or not verify_password(stored.password_hash, payload.password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password is incorrect")
        organization = await session.get(Organization, stored.organization_id)
        if organization is None:
            await session.execute(delete(AuthSession).where(AuthSession.user_id == stored.id))
            await session.delete(stored)
            return
        await session.delete(organization)
