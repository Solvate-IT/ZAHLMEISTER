from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import get_organization
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import BankSyncAccount, BankSyncConnection, Organization
from app.schemas.bank_sync import (
    BankSyncAccountRead,
    BankSyncAccountUpdate,
    BankSyncConnectionRead,
    BankSyncRunRead,
    BankSyncStartRead,
    BankSyncTestRead,
    PontoConfigurationRead,
)
from app.services import ponto
from app.services.bank_sync import refresh_accounts, sync_connection
from app.services.bank_sync_providers import get_bank_sync_provider

router = APIRouter(prefix="/bank-sync", tags=["bank-sync"])


def _connection_read(item: BankSyncConnection) -> BankSyncConnectionRead:
    return BankSyncConnectionRead(
        id=item.id,
        provider=item.provider,
        status=item.status,
        account_label=item.account_label,
        connected_at=item.connected_at,
        last_sync_at=item.last_sync_at,
        last_tested_at=item.last_tested_at,
        last_error=item.last_error,
    )


def _account_read(item: BankSyncAccount) -> BankSyncAccountRead:
    return BankSyncAccountRead(
        id=item.id,
        external_id=item.external_id,
        name=item.name,
        iban=item.iban,
        currency=item.currency,
        enabled=item.enabled,
        last_sync_at=item.last_sync_at,
    )


def _ponto_redirect(result: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.public_app_url.rstrip('/')}?ponto={result}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/connection", response_model=BankSyncConnectionRead | None)
async def get_connection(organization: Organization = Depends(get_organization)):
    async with SessionLocal() as session:
        item = await session.scalar(
            select(BankSyncConnection).where(
                BankSyncConnection.organization_id == organization.id,
                BankSyncConnection.provider == "ponto",
            )
        )
        if item is None or item.status == "disconnected":
            return None
        return _connection_read(item)


@router.get("/ponto/configuration", response_model=PontoConfigurationRead)
async def get_ponto_configuration(
    organization: Organization = Depends(get_organization),
) -> PontoConfigurationRead:
    del organization
    return PontoConfigurationRead(**ponto.configuration_status())


@router.post("/ponto/start", response_model=BankSyncStartRead)
async def start_ponto(organization: Organization = Depends(get_organization)) -> BankSyncStartRead:
    authorization_url: str | None = None
    error_detail: str | None = None
    async with SessionLocal.begin() as session:
        item = await session.scalar(
            select(BankSyncConnection).where(
                BankSyncConnection.organization_id == organization.id,
                BankSyncConnection.provider == "ponto",
            )
        )
        if item is None:
            item = BankSyncConnection(
                organization_id=organization.id,
                provider="ponto",
                status="connecting",
                account_label="Ponto",
            )
            session.add(item)
            await session.flush()
        item.status = "connecting"
        item.account_label = item.account_label or "Ponto"
        item.last_error = None
        try:
            language = (organization.locale or "en").split("-", 1)[0]
            authorization_url = ponto.start_authorization(
                item, str(organization.id), language
            )
        except ValueError as exc:
            error_detail = str(exc)
            item.status = "error"
            item.last_error = error_detail[:2000]
            item.last_tested_at = datetime.now(UTC)

    if error_detail:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=error_detail
        )
    assert authorization_url is not None
    return BankSyncStartRead(authorization_url=authorization_url)


@router.get("/ponto/callback", include_in_schema=False)
async def finish_ponto(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if not state:
        return _ponto_redirect("error")

    try:
        connection_id_raw, organization_id_raw = ponto.verify_state(state)
        connection_id = UUID(connection_id_raw)
        organization_id = UUID(organization_id_raw)
    except (ValueError, TypeError):
        return _ponto_redirect("error")

    result = "error"
    async with SessionLocal.begin() as session:
        item = await session.get(BankSyncConnection, connection_id, with_for_update=True)
        if item is None or item.organization_id != organization_id:
            return _ponto_redirect("error")

        now = datetime.now(UTC)
        if error:
            cancelled = error == "access_denied"
            item.status = "disconnected" if cancelled else "error"
            description = (error_description or error).replace("\r", " ").replace("\n", " ").strip()
            item.last_error = description[:2000] if description else "Ponto authorization failed"
            item.last_tested_at = now
            result = "cancelled" if cancelled else "error"
        elif not code:
            item.status = "error"
            item.last_error = "Ponto authorization code is missing"
            item.last_tested_at = now
        else:
            try:
                await ponto.exchange_code(item, code)
                await refresh_accounts(session, item)
                item.status = "connected"
                item.last_error = None
                item.last_tested_at = now
                result = "connected"
            except Exception as exc:
                item.status = "error"
                item.last_error = str(exc)[:2000]
                item.last_tested_at = now

    return _ponto_redirect(result)


@router.post("/connection/test", response_model=BankSyncTestRead)
async def test_connection(organization: Organization = Depends(get_organization)) -> BankSyncTestRead:
    tested_at = datetime.now(UTC)
    async with SessionLocal.begin() as session:
        item = await session.scalar(
            select(BankSyncConnection).where(
                BankSyncConnection.organization_id == organization.id,
                BankSyncConnection.provider == "ponto",
            )
        )
        if item is None or item.status == "disconnected":
            raise HTTPException(status_code=404, detail="BankSync is not connected")
        try:
            await get_bank_sync_provider(item.provider).test_connection(item)
        except Exception as exc:
            item.status = "error"
            item.last_error = str(exc)[:2000]
            item.last_tested_at = tested_at
            return BankSyncTestRead(ok=False, status="error", tested_at=tested_at, error=item.last_error)
        item.status = "connected"
        item.last_error = None
        item.last_tested_at = tested_at
        return BankSyncTestRead(ok=True, status="connected", tested_at=tested_at)


@router.get("/accounts", response_model=list[BankSyncAccountRead])
async def get_accounts(organization: Organization = Depends(get_organization)) -> list[BankSyncAccountRead]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(BankSyncAccount)
                .where(BankSyncAccount.organization_id == organization.id)
                .order_by(BankSyncAccount.name, BankSyncAccount.iban)
            )
        ).scalars().all()
        return [_account_read(item) for item in rows]


@router.put("/accounts/{account_id}", response_model=BankSyncAccountRead)
async def update_account(
    account_id: UUID,
    payload: BankSyncAccountUpdate,
    organization: Organization = Depends(get_organization),
) -> BankSyncAccountRead:
    async with SessionLocal.begin() as session:
        item = await session.get(BankSyncAccount, account_id, with_for_update=True)
        if item is None or item.organization_id != organization.id:
            raise HTTPException(status_code=404, detail="Bank account not found")
        item.enabled = payload.enabled
        await session.flush()
        await session.refresh(item)
        return _account_read(item)


@router.post("/sync", response_model=BankSyncRunRead)
async def sync_now(organization: Organization = Depends(get_organization)) -> BankSyncRunRead:
    async with SessionLocal.begin() as session:
        item = await session.scalar(
            select(BankSyncConnection).where(
                BankSyncConnection.organization_id == organization.id,
                BankSyncConnection.provider == "ponto",
            )
        )
        if item is None or item.status not in {"connected", "error"}:
            raise HTTPException(status_code=409, detail="BankSync is not connected")
        try:
            result = await sync_connection(session, item)
        except Exception as exc:
            item.status = "error"
            item.last_error = str(exc)[:2000]
            raise HTTPException(status_code=502, detail=item.last_error) from exc
        return BankSyncRunRead(**result)


@router.delete("/connection", status_code=204)
async def disconnect(organization: Organization = Depends(get_organization)) -> None:
    async with SessionLocal.begin() as session:
        item = await session.scalar(
            select(BankSyncConnection)
            .where(
                BankSyncConnection.organization_id == organization.id,
                BankSyncConnection.provider == "ponto",
            )
            .with_for_update()
        )
        if item is None or item.status == "disconnected":
            return
        # Keep connection/account rows because historical BankTransaction records point
        # to those accounts. Removing only the credentials stops access while retaining
        # the financial audit trail and the user's previous account enable/disable choices.
        item.status = "disconnected"
        item.encrypted_config = None
        item.connected_at = None
        item.last_tested_at = None
        item.last_error = None
