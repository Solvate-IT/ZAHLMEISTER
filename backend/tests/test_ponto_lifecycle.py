import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.secrets import encrypt_config


def test_ponto_revoke_url_follows_oauth_token_endpoint(monkeypatch) -> None:
    from app.services import ponto

    monkeypatch.setattr(
        ponto.settings,
        "ponto_connect_token_url",
        "https://api.ibanity.com/ponto-connect/oauth2/token",
    )
    assert ponto._revoke_url() == "https://api.ibanity.com/ponto-connect/oauth2/revoke"


@pytest.mark.asyncio
async def test_ponto_disconnect_revokes_refresh_token_with_mtls_and_basic_auth(monkeypatch) -> None:
    from app.services import ponto

    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *args, **kwargs):
            calls.append(("client", kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    monkeypatch.setattr(ponto.httpx, "AsyncClient", Client)
    monkeypatch.setattr(ponto, "_ssl_context", lambda: "ssl-context")
    monkeypatch.setattr(
        ponto.settings,
        "ponto_connect_token_url",
        "https://api.ibanity.com/ponto-connect/oauth2/token",
    )
    monkeypatch.setattr(ponto.settings, "ponto_connect_client_id", "client-id")
    monkeypatch.setattr(ponto.settings, "ponto_connect_client_secret", "client-secret")
    monkeypatch.setattr(ponto.settings, "ponto_connect_environment", "sandbox")

    connection = SimpleNamespace(
        encrypted_config=encrypt_config(
            {
                "refresh_token": "refresh-token",
                "ponto_environment": "sandbox",
            }
        )
    )
    await ponto.revoke_connection(connection)

    assert calls[0] == ("client", {"verify": "ssl-context", "timeout": 30})
    url, request = calls[1]
    assert url == "https://api.ibanity.com/ponto-connect/oauth2/revoke"
    assert request["data"] == {"token": "refresh-token"}
    expected = "Basic " + base64.b64encode(b"client-id:client-secret").decode()
    assert request["headers"]["Authorization"] == expected


@pytest.mark.asyncio
async def test_ponto_disconnect_does_not_silently_drop_missing_remote_token() -> None:
    from app.services import ponto

    connection = SimpleNamespace(
        encrypted_config=encrypt_config({"ponto_environment": "sandbox"})
    )
    with pytest.raises(ValueError, match="revoke the integration in Ponto"):
        await ponto.revoke_connection(connection)


@pytest.mark.asyncio
async def test_ponto_start_rejects_incomplete_configuration_before_database_write(monkeypatch) -> None:
    from app.api.routes import bank_sync

    monkeypatch.setattr(
        bank_sync.ponto,
        "configuration_status",
        lambda: {
            "environment": "sandbox",
            "configured": False,
            "redirect_uri": "https://example.test/callback",
            "missing": ["client_id", "client_secret"],
        },
    )

    class SessionMustNotBeUsed:
        async def scalar(self, _statement):
            raise AssertionError("database was used before Ponto readiness was checked")

    organization = SimpleNamespace(id=uuid4(), locale="de-AT")

    with pytest.raises(HTTPException) as exc:
        await bank_sync.start_ponto(organization, SessionMustNotBeUsed())

    assert exc.value.status_code == 409
    assert "client_id" in str(exc.value.detail)
    assert "client_secret" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_failed_ponto_onboarding_row_is_hidden_without_mutating_database() -> None:
    from app.api.routes import bank_sync

    connection = SimpleNamespace(
        id=uuid4(),
        provider="ponto",
        status="error",
        connected_at=None,
    )

    class Session:
        async def scalar(self, _statement):
            return connection

    organization = SimpleNamespace(id=uuid4())

    assert await bank_sync.get_connection(organization, Session()) is None


@pytest.mark.asyncio
async def test_disconnect_of_unestablished_ponto_row_is_local_only(monkeypatch) -> None:
    from app.api.routes import bank_sync

    connection = SimpleNamespace(
        id=uuid4(),
        provider="ponto",
        status="error",
        connected_at=None,
        encrypted_config="secret",
        last_sync_at=None,
        last_tested_at=None,
        last_error="old error",
    )

    class Session:
        async def scalar(self, _statement):
            return connection

    class Context:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *args):
            return False

    class SessionFactory:
        def begin(self):
            return Context()

    async def must_not_revoke(_connection):
        raise AssertionError("remote revocation must not run without a completed OAuth connection")

    monkeypatch.setattr(bank_sync, "SessionLocal", SessionFactory())
    monkeypatch.setattr(bank_sync.ponto, "revoke_connection", must_not_revoke)
    organization = SimpleNamespace(id=uuid4())

    await bank_sync.disconnect(organization)
    assert connection.status == "disconnected"
    assert connection.encrypted_config is None
    assert connection.connected_at is None
