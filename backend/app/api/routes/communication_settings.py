import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import get_organization
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import (
    CommunicationChannelSetting,
    CommunicationConnection,
    Organization,
)
from app.schemas.communications import (
    ChannelSettingRead,
    ChannelSettingUpdate,
    CommunicationConnectionRead,
    CommunicationConnectionUpdate,
    ConnectionTestRead,
    InfobipConnectRequest,
    InfobipOAuthStartRead,
    Microsoft365OAuthStartRead,
)
from app.services import microsoft365
from app.services.channel_config import SECRET_FIELDS, SUPPORTED_CHANNELS, internal_channel_configured
from app.services.communications import test_smtp_imap
from app.services.infobip import (
    connection_is_active,
    connection_webhook_url,
    exchange_oauth_code,
    oauth_authorization_url,
    oauth_connection_config,
    test_connection as test_infobip_connection,
    validate_api_key,
    verify_oauth_state,
)
from app.services.secrets import decrypt_config, encrypt_config

router = APIRouter(prefix="/communication-settings", tags=["communication-settings"])


def _connection_read(connection: CommunicationConnection) -> CommunicationConnectionRead:
    config = decrypt_config(connection.encrypted_config)
    return CommunicationConnectionRead(
        id=connection.id,
        provider=connection.provider,
        auth_type=connection.auth_type,
        status=connection.status,
        account_label=connection.account_label,
        account_key=connection.account_key,
        base_url=str(config.get("base_url") or "") or None,
        connected_at=connection.connected_at,
        last_error=connection.last_error,
        last_tested_at=connection.last_tested_at,
    )


def _safe_email_fields(config: dict) -> dict:
    result: dict = {}
    for key, value in config.items():
        if key in SECRET_FIELDS["email"]:
            result[f"{key}_configured"] = bool(value)
        else:
            result[key] = value
    return result


def _connection_active(connection: CommunicationConnection | None) -> bool:
    return bool(connection and connection.status == "connected")


def _read(
    channel: str,
    stored: CommunicationChannelSetting | None,
    connections: dict[UUID, CommunicationConnection],
) -> ChannelSettingRead:
    if stored is None:
        return ChannelSettingRead(
            channel=channel,
            mode="external",
            configured=True,
            fields={},
        )

    config = decrypt_config(stored.encrypted_config)
    connection = connections.get(stored.connection_id) if stored.connection_id else None
    active = (
        _connection_active(connection)
        if stored.provider == "microsoft365"
        else connection_is_active(connection)
    )
    configured = stored.mode != "internal" or internal_channel_configured(
        channel,
        provider=stored.provider,
        config=config,
        connection_active=active,
        sender=stored.sender,
    )
    webhook_url = (
        connection_webhook_url(connection.webhook_key)
        if connection and connection.provider == "infobip" and connection.webhook_key
        else None
    )
    return ChannelSettingRead(
        channel=channel,
        mode=stored.mode,
        provider=stored.provider,
        configured=configured,
        sender=stored.sender,
        connection_id=stored.connection_id,
        fields=_safe_email_fields(config)
        if channel == "email" and stored.provider == "smtp_imap"
        else {},
        webhook_url=webhook_url,
        status=stored.status,
        last_tested_at=stored.last_tested_at,
        last_error=stored.last_error,
    )


@router.get("/connections", response_model=list[CommunicationConnectionRead])
async def get_connections(
    organization: Organization = Depends(get_organization),
) -> list[CommunicationConnectionRead]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(CommunicationConnection)
                .where(CommunicationConnection.organization_id == organization.id)
                .order_by(CommunicationConnection.created_at)
            )
        ).scalars().all()
        return [_connection_read(row) for row in rows]


@router.post(
    "/infobip/api-key",
    response_model=CommunicationConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def connect_infobip_api_key(
    payload: InfobipConnectRequest,
    organization: Organization = Depends(get_organization),
) -> CommunicationConnectionRead:
    try:
        await validate_api_key(payload.base_url, payload.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    async with SessionLocal.begin() as session:
        existing = await session.scalar(
            select(CommunicationConnection).where(
                CommunicationConnection.organization_id == organization.id,
                CommunicationConnection.provider == "infobip",
            )
        )
        connection = existing or CommunicationConnection(
            organization_id=organization.id,
            provider="infobip",
        )
        if existing is None:
            session.add(connection)
        connection.auth_type = "api_key"
        connection.status = "connected"
        connection.account_label = payload.account_label or "Infobip"
        connection.encrypted_config = encrypt_config(
            {"api_key": payload.api_key, "base_url": payload.base_url}
        )
        connection.webhook_key = connection.webhook_key or secrets.token_urlsafe(32)
        connection.connected_at = datetime.now(UTC)
        connection.last_error = None
        connection.last_tested_at = None
        await session.flush()
        await session.refresh(connection)
        return _connection_read(connection)


@router.get("/infobip/oauth/start", response_model=InfobipOAuthStartRead)
async def start_infobip_oauth(
    organization: Organization = Depends(get_organization),
) -> InfobipOAuthStartRead:
    try:
        url = oauth_authorization_url(str(organization.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InfobipOAuthStartRead(authorization_url=url)


@router.get("/infobip/oauth/callback", include_in_schema=False)
async def finish_infobip_oauth(code: str, state: str):
    try:
        organization_id = UUID(verify_oauth_state(state))
        payload = await exchange_oauth_code(code)
    except Exception:
        return RedirectResponse(
            f"{settings.public_app_url.rstrip('/')}?infobip=error",
            status_code=status.HTTP_302_FOUND,
        )

    async with SessionLocal.begin() as session:
        organization = await session.get(Organization, organization_id)
        if organization is None:
            return RedirectResponse(
                f"{settings.public_app_url.rstrip('/')}?infobip=error",
                status_code=status.HTTP_302_FOUND,
            )
        existing = await session.scalar(
            select(CommunicationConnection).where(
                CommunicationConnection.organization_id == organization.id,
                CommunicationConnection.provider == "infobip",
            )
        )
        connection = existing or CommunicationConnection(
            organization_id=organization.id,
            provider="infobip",
        )
        if existing is None:
            session.add(connection)
        connection.auth_type = "oauth"
        connection.status = "connected"
        connection.account_label = str(payload.get("email") or payload.get("username") or "Infobip")
        connection.account_key = str(payload.get("accountKey") or "") or None
        connection.encrypted_config = encrypt_config(oauth_connection_config(payload))
        connection.webhook_key = connection.webhook_key or secrets.token_urlsafe(32)
        connection.connected_at = datetime.now(UTC)
        connection.last_error = None

    return RedirectResponse(
        f"{settings.public_app_url.rstrip('/')}?infobip=connected",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/microsoft365/oauth/start", response_model=Microsoft365OAuthStartRead)
async def start_microsoft365_oauth(
    organization: Organization = Depends(get_organization),
) -> Microsoft365OAuthStartRead:
    async with SessionLocal.begin() as session:
        connection = await session.scalar(
            select(CommunicationConnection).where(
                CommunicationConnection.organization_id == organization.id,
                CommunicationConnection.provider == "microsoft365",
            )
        )
        if connection is None:
            connection = CommunicationConnection(
                organization_id=organization.id,
                provider="microsoft365",
                auth_type="oauth",
                status="connecting",
                account_label="Microsoft 365",
            )
            session.add(connection)
            await session.flush()
        connection.auth_type = "oauth"
        connection.status = "connecting"
        connection.last_error = None
        try:
            url = microsoft365.authorization_url(connection, str(organization.id))
        except ValueError as exc:
            connection.status = "error"
            connection.last_error = str(exc)[:2000]
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return Microsoft365OAuthStartRead(authorization_url=url)


def _microsoft_redirect(result: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.public_app_url.rstrip('/')}?microsoft365={result}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/microsoft365/oauth/callback", include_in_schema=False)
async def finish_microsoft365_oauth(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if not state:
        return _microsoft_redirect("error")
    try:
        connection_id_raw, organization_id_raw = microsoft365.verify_state(state)
        connection_id = UUID(connection_id_raw)
        organization_id = UUID(organization_id_raw)
    except (ValueError, TypeError):
        return _microsoft_redirect("error")

    if error:
        async with SessionLocal.begin() as session:
            connection = await session.get(CommunicationConnection, connection_id, with_for_update=True)
            if connection and connection.organization_id == organization_id:
                connection.status = "disconnected" if error == "access_denied" else "error"
                connection.last_error = (error_description or error)[:2000]
                connection.last_tested_at = datetime.now(UTC)
        return _microsoft_redirect("cancelled" if error == "access_denied" else "error")
    if not code:
        return _microsoft_redirect("error")

    try:
        async with SessionLocal.begin() as session:
            connection = await session.get(CommunicationConnection, connection_id, with_for_update=True)
            if (
                connection is None
                or connection.organization_id != organization_id
                or connection.provider != "microsoft365"
            ):
                raise ValueError("Microsoft 365 connection not found")
            await microsoft365.exchange_code(connection, code)
            connection.status = "connected"
            connection.connected_at = datetime.now(UTC)
            connection.last_error = None

        profile = await microsoft365.profile(connection_id)
        async with SessionLocal.begin() as session:
            connection = await session.get(CommunicationConnection, connection_id, with_for_update=True)
            if connection is None or connection.organization_id != organization_id:
                raise ValueError("Microsoft 365 connection not found")
            mailbox = str(profile.get("mail") or profile.get("userPrincipalName") or "").strip()
            connection.account_label = mailbox or str(profile.get("displayName") or "Microsoft 365")
            connection.account_key = str(profile.get("id") or "") or None
            connection.status = "connected"
            connection.connected_at = connection.connected_at or datetime.now(UTC)
            connection.last_error = None
            connection.last_tested_at = datetime.now(UTC)
        return _microsoft_redirect("connected")
    except Exception as exc:
        async with SessionLocal.begin() as session:
            connection = await session.get(CommunicationConnection, connection_id, with_for_update=True)
            if connection and connection.organization_id == organization_id:
                connection.status = "error"
                connection.last_error = str(exc)[:2000]
                connection.last_tested_at = datetime.now(UTC)
        return _microsoft_redirect("error")


@router.patch("/connections/{connection_id}", response_model=CommunicationConnectionRead)
async def update_connection(
    connection_id: UUID,
    payload: CommunicationConnectionUpdate,
    organization: Organization = Depends(get_organization),
) -> CommunicationConnectionRead:
    async with SessionLocal.begin() as session:
        connection = await session.get(CommunicationConnection, connection_id, with_for_update=True)
        if connection is None or connection.organization_id != organization.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
        if connection.provider != "infobip":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only Infobip connections can be edited here",
            )
        config = decrypt_config(connection.encrypted_config)
        if payload.base_url is not None:
            config["base_url"] = payload.base_url
        if payload.account_label is not None:
            connection.account_label = payload.account_label.strip() or "Infobip"
        connection.encrypted_config = encrypt_config(config)
        connection.last_error = None
        await session.flush()
        await session.refresh(connection)
        return _connection_read(connection)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_connection(
    connection_id: UUID,
    organization: Organization = Depends(get_organization),
) -> None:
    async with SessionLocal.begin() as session:
        connection = await session.get(CommunicationConnection, connection_id)
        if connection is None or connection.organization_id != organization.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
        settings_rows = (
            await session.execute(
                select(CommunicationChannelSetting).where(
                    CommunicationChannelSetting.organization_id == organization.id,
                    CommunicationChannelSetting.connection_id == connection.id,
                )
            )
        ).scalars().all()
        for row in settings_rows:
            row.mode = "external"
            row.provider = None
            row.connection_id = None
            row.sender = None
            row.encrypted_config = None
            row.status = "not_tested"
            row.sync_cursor = None
        await session.delete(connection)


@router.post("/connections/{connection_id}/test", response_model=ConnectionTestRead)
async def test_connection_endpoint(
    connection_id: UUID,
    organization: Organization = Depends(get_organization),
) -> ConnectionTestRead:
    tested_at = datetime.now(UTC)
    async with SessionLocal.begin() as session:
        connection = await session.get(CommunicationConnection, connection_id, with_for_update=True)
        if connection is None or connection.organization_id != organization.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
        try:
            details: dict[str, str] = {}
            if connection.provider == "infobip":
                await test_infobip_connection(session, connection)
            elif connection.provider == "microsoft365":
                details = await microsoft365.test_connection(connection.id)
            else:
                raise ValueError("Unsupported provider")
        except Exception as exc:
            connection.status = "error"
            connection.last_error = str(exc)[:2000]
            connection.last_tested_at = tested_at
            return ConnectionTestRead(
                ok=False, status="error", tested_at=tested_at, error=connection.last_error
            )
        connection.status = "connected"
        connection.last_error = None
        connection.last_tested_at = tested_at
        return ConnectionTestRead(
            ok=True, status="connected", tested_at=tested_at, details=details
        )


@router.post("/{channel}/test", response_model=ConnectionTestRead)
async def test_channel_endpoint(
    channel: str,
    organization: Organization = Depends(get_organization),
) -> ConnectionTestRead:
    if channel not in SUPPORTED_CHANNELS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown channel")
    tested_at = datetime.now(UTC)
    async with SessionLocal.begin() as session:
        stored = await session.scalar(
            select(CommunicationChannelSetting).where(
                CommunicationChannelSetting.organization_id == organization.id,
                CommunicationChannelSetting.channel == channel,
            )
        )
        if stored is None or stored.mode != "internal":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Internal channel is not enabled")
        try:
            details: dict[str, str] = {}
            if stored.provider == "smtp_imap":
                details = await test_smtp_imap(decrypt_config(stored.encrypted_config))
            elif stored.provider == "infobip":
                if stored.connection_id is None:
                    raise ValueError("Infobip connection missing")
                connection = await session.get(CommunicationConnection, stored.connection_id, with_for_update=True)
                if connection is None:
                    raise ValueError("Infobip connection missing")
                await test_infobip_connection(session, connection)
                connection.status = "connected"
                connection.last_error = None
                connection.last_tested_at = tested_at
            elif stored.provider == "microsoft365":
                if stored.connection_id is None:
                    raise ValueError("Microsoft 365 connection missing")
                connection = await session.get(CommunicationConnection, stored.connection_id, with_for_update=True)
                if connection is None or connection.provider != "microsoft365":
                    raise ValueError("Microsoft 365 connection missing")
                details = await microsoft365.test_connection(connection.id)
                connection.status = "connected"
                connection.last_error = None
                connection.last_tested_at = tested_at
            else:
                raise ValueError("Unsupported internal provider")
        except Exception as exc:
            stored.status = "error"
            stored.last_error = str(exc)[:2000]
            stored.last_tested_at = tested_at
            return ConnectionTestRead(
                ok=False, status="error", tested_at=tested_at, error=stored.last_error
            )
        stored.status = "ok"
        stored.last_error = None
        stored.last_tested_at = tested_at
        return ConnectionTestRead(ok=True, status="ok", tested_at=tested_at, details=details)


@router.get("", response_model=list[ChannelSettingRead])
async def get_settings(organization: Organization = Depends(get_organization)) -> list[ChannelSettingRead]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(CommunicationChannelSetting).where(
                    CommunicationChannelSetting.organization_id == organization.id
                )
            )
        ).scalars().all()
        connections = (
            await session.execute(
                select(CommunicationConnection).where(
                    CommunicationConnection.organization_id == organization.id
                )
            )
        ).scalars().all()
    by_channel = {row.channel: row for row in rows}
    by_connection = {row.id: row for row in connections}
    return [_read(channel, by_channel.get(channel), by_connection) for channel in SUPPORTED_CHANNELS]


@router.put("/{channel}", response_model=ChannelSettingRead)
async def update_setting(
    channel: str,
    payload: ChannelSettingUpdate,
    organization: Organization = Depends(get_organization),
) -> ChannelSettingRead:
    if channel not in SUPPORTED_CHANNELS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown channel")

    provider = payload.provider
    if payload.mode == "external":
        provider = None
    elif channel == "email":
        provider = provider or "smtp_imap"
        if provider not in {"smtp_imap", "infobip", "microsoft365"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Internal email supports Microsoft 365, Infobip or own SMTP/IMAP",
            )
    else:
        provider = "infobip"

    async with SessionLocal.begin() as session:
        connection = None
        if payload.mode == "internal" and provider in {"infobip", "microsoft365"}:
            if payload.connection_id is None:
                name = "Infobip" if provider == "infobip" else "Microsoft 365"
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Connect a {name} account first",
                )
            connection = await session.get(CommunicationConnection, payload.connection_id)
            if (
                connection is None
                or connection.organization_id != organization.id
                or connection.provider != provider
                or connection.status != "connected"
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{provider} connection is not active",
                )
            if provider == "infobip" and not payload.sender:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Select or enter the Infobip sender/resource for this channel",
                )

        stored = await session.scalar(
            select(CommunicationChannelSetting).where(
                CommunicationChannelSetting.organization_id == organization.id,
                CommunicationChannelSetting.channel == channel,
            )
        )
        if stored is None:
            stored = CommunicationChannelSetting(
                organization_id=organization.id,
                channel=channel,
                mode=payload.mode,
            )
            session.add(stored)
            existing = {}
        else:
            existing = decrypt_config(stored.encrypted_config)

        incoming = dict(payload.fields) if channel == "email" and provider == "smtp_imap" else {}
        if provider == "smtp_imap":
            for secret_field in SECRET_FIELDS["email"]:
                incoming.pop(f"{secret_field}_configured", None)
                value = incoming.get(secret_field)
                if value in (None, ""):
                    incoming.pop(secret_field, None)
                if secret_field not in incoming and secret_field in existing:
                    incoming[secret_field] = existing[secret_field]

        stored.mode = payload.mode
        stored.provider = provider
        stored.connection_id = connection.id if connection else None
        stored.sender = payload.sender if provider == "infobip" else None
        stored.encrypted_config = encrypt_config(incoming) if incoming else None
        stored.webhook_key = None
        stored.sync_cursor = None if provider != "smtp_imap" else stored.sync_cursor
        stored.status = "not_tested"
        stored.last_tested_at = None
        stored.last_error = None
        await session.flush()
        await session.refresh(stored)
        connections = {connection.id: connection} if connection else {}
        return _read(channel, stored, connections)
