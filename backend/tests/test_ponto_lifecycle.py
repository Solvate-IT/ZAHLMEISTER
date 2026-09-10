import base64
from types import SimpleNamespace

import pytest

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
