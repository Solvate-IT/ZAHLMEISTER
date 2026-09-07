from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import get_organization
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import OnlinePaymentConnection, Organization
from app.schemas.online_payments import (
    OnlinePaymentConnectionRead,
    OnlinePaymentEnabledUpdate,
    OnlinePaymentOAuthStartRead,
    OnlinePaymentProfileRead,
    OnlinePaymentProfileUpdate,
    OnlinePaymentTestRead,
)
from app.services.mollie import (
    PROVIDER,
    exchange_oauth_code,
    get_account_details,
    mollie_provider,
    oauth_authorization_url,
    oauth_connection_config,
    revoke_connection,
    verify_oauth_state,
)
from app.services.secrets import encrypt_config

router = APIRouter(prefix="/online-payments", tags=["online-payments"])


def _read(connection: OnlinePaymentConnection) -> OnlinePaymentConnectionRead:
    return OnlinePaymentConnectionRead(
        id=connection.id,
        provider=connection.provider,
        status=connection.status,
        enabled=connection.enabled,
        account_label=connection.account_label,
        profile_id=connection.profile_id,
        connected_at=connection.connected_at,
        last_tested_at=connection.last_tested_at,
        last_error=connection.last_error,
    )


async def _get_connection(session, organization_id: UUID, *, for_update: bool = False):
    stmt = select(OnlinePaymentConnection).where(
        OnlinePaymentConnection.organization_id == organization_id,
        OnlinePaymentConnection.provider == PROVIDER,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


@router.get("/connection", response_model=OnlinePaymentConnectionRead | None)
async def get_connection(
    organization: Organization = Depends(get_organization),
) -> OnlinePaymentConnectionRead | None:
    async with SessionLocal() as session:
        connection = await _get_connection(session, organization.id)
        return _read(connection) if connection else None


@router.get("/mollie/oauth/start", response_model=OnlinePaymentOAuthStartRead)
async def start_mollie_oauth(
    organization: Organization = Depends(get_organization),
) -> OnlinePaymentOAuthStartRead:
    try:
        url = oauth_authorization_url(str(organization.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return OnlinePaymentOAuthStartRead(authorization_url=url)


@router.get("/mollie/oauth/callback", include_in_schema=False)
async def finish_mollie_oauth(
    state: str,
    code: str | None = None,
    authorization_code: str | None = None,
    error: str | None = None,
):
    if error:
        return RedirectResponse(
            f"{settings.public_app_url.rstrip('/')}?mollie=error",
            status_code=status.HTTP_302_FOUND,
        )
    auth_code = code or authorization_code
    if not auth_code:
        return RedirectResponse(
            f"{settings.public_app_url.rstrip('/')}?mollie=error",
            status_code=status.HTTP_302_FOUND,
        )
    try:
        organization_id = UUID(verify_oauth_state(state))
        payload = await exchange_oauth_code(auth_code)
    except Exception:
        return RedirectResponse(
            f"{settings.public_app_url.rstrip('/')}?mollie=error",
            status_code=status.HTTP_302_FOUND,
        )

    async with SessionLocal.begin() as session:
        organization = await session.get(Organization, organization_id)
        if organization is None:
            return RedirectResponse(
                f"{settings.public_app_url.rstrip('/')}?mollie=error",
                status_code=status.HTTP_302_FOUND,
            )
        connection = await _get_connection(session, organization.id, for_update=True)
        if connection is None:
            connection = OnlinePaymentConnection(
                organization_id=organization.id,
                provider=PROVIDER,
                status="connecting",
            )
            session.add(connection)
            await session.flush()
        connection.encrypted_config = encrypt_config(oauth_connection_config(payload))
        connection.status = "connected"
        connection.enabled = True
        connection.connected_at = datetime.now(UTC)
        connection.last_error = None
        connection.last_tested_at = None
        try:
            account_label, profiles = await get_account_details(session, connection)
            connection.account_label = account_label or "Mollie"
            if profiles and not connection.profile_id:
                connection.profile_id = str(profiles[0]["id"])
        except Exception as exc:
            connection.status = "error"
            connection.last_error = str(exc)[:2000]

    result = "connected" if connection.status == "connected" else "error"
    return RedirectResponse(
        f"{settings.public_app_url.rstrip('/')}?mollie={result}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/profiles", response_model=list[OnlinePaymentProfileRead])
async def list_profiles(
    organization: Organization = Depends(get_organization),
) -> list[OnlinePaymentProfileRead]:
    async with SessionLocal.begin() as session:
        connection = await _get_connection(session, organization.id, for_update=True)
        if connection is None:
            raise HTTPException(status_code=404, detail="Online payment connection not found")
        try:
            _, profiles = await get_account_details(session, connection)
        except Exception as exc:
            connection.status = "error"
            connection.last_error = str(exc)[:2000]
            raise HTTPException(status_code=502, detail=connection.last_error) from exc
        return [
            OnlinePaymentProfileRead(
                id=str(item["id"]),
                name=str(item["name"] or item["id"]),
                website=item.get("website"),
                status=item.get("status"),
                selected=str(item["id"]) == connection.profile_id,
            )
            for item in profiles
        ]


@router.put("/profile", response_model=OnlinePaymentConnectionRead)
async def select_profile(
    payload: OnlinePaymentProfileUpdate,
    organization: Organization = Depends(get_organization),
) -> OnlinePaymentConnectionRead:
    async with SessionLocal.begin() as session:
        connection = await _get_connection(session, organization.id, for_update=True)
        if connection is None:
            raise HTTPException(status_code=404, detail="Online payment connection not found")
        try:
            _, profiles = await get_account_details(session, connection)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not any(str(item["id"]) == payload.profile_id for item in profiles):
            raise HTTPException(status_code=422, detail="Mollie payment profile not available")
        connection.profile_id = payload.profile_id
        connection.status = "connected"
        connection.last_error = None
        await session.flush()
        await session.refresh(connection)
        return _read(connection)


@router.put("/enabled", response_model=OnlinePaymentConnectionRead)
async def set_enabled(
    payload: OnlinePaymentEnabledUpdate,
    organization: Organization = Depends(get_organization),
) -> OnlinePaymentConnectionRead:
    async with SessionLocal.begin() as session:
        connection = await _get_connection(session, organization.id, for_update=True)
        if connection is None:
            raise HTTPException(status_code=404, detail="Online payment connection not found")
        connection.enabled = payload.enabled
        await session.flush()
        await session.refresh(connection)
        return _read(connection)


@router.post("/connection/test", response_model=OnlinePaymentTestRead)
async def test_connection(
    organization: Organization = Depends(get_organization),
) -> OnlinePaymentTestRead:
    tested_at = datetime.now(UTC)
    async with SessionLocal.begin() as session:
        connection = await _get_connection(session, organization.id, for_update=True)
        if connection is None:
            raise HTTPException(status_code=404, detail="Online payment connection not found")
        try:
            await mollie_provider.test_connection(session, connection)
            connection.status = "connected"
            connection.last_error = None
            ok = True
            error_text = None
        except Exception as exc:
            connection.status = "error"
            connection.last_error = str(exc)[:2000]
            ok = False
            error_text = connection.last_error
        connection.last_tested_at = tested_at
        return OnlinePaymentTestRead(
            ok=ok,
            status=connection.status,
            tested_at=tested_at,
            error=error_text,
        )


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    organization: Organization = Depends(get_organization),
) -> None:
    async with SessionLocal.begin() as session:
        connection = await _get_connection(session, organization.id, for_update=True)
        if connection is None:
            return
        await revoke_connection(connection)
        await session.delete(connection)
