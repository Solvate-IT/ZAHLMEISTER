import base64
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.communications import CommunicationConnectionUpdate
from app.services.infobip import (
    INFOBIP_WHATSAPP_TEMPLATE_NAME,
    ensure_event_subscription,
    sign_oauth_state,
    verify_oauth_state,
    verify_webhook_basic_authorization,
)
from app.services.message_renderer import CanonicalMessage
from app.services.secrets import decrypt_config, encrypt_config


def test_infobip_oauth_state_round_trip() -> None:
    organization_id = "35339f45-b856-4f3c-a355-4a27a21f00d8"
    state = sign_oauth_state(organization_id)
    assert verify_oauth_state(state) == organization_id


def test_infobip_oauth_state_rejects_tampering() -> None:
    state = sign_oauth_state("org")
    body, signature = state.split(".", 1)
    tampered = f"{body}.{signature[:-1]}x"
    with pytest.raises(ValueError, match="Invalid OAuth state"):
        verify_oauth_state(tampered)


def test_infobip_connection_update_requires_https_base_url() -> None:
    value = CommunicationConnectionUpdate(base_url="https://abc.api.infobip.com/")
    assert value.base_url == "https://abc.api.infobip.com"
    with pytest.raises(ValidationError):
        CommunicationConnectionUpdate(base_url="http://abc.api.infobip.com")


def test_delivery_status_never_regresses_after_stronger_evidence() -> None:
    from app.api.routes.webhooks import _advanced_delivery_status

    assert _advanced_delivery_status("sent", "failed") == "failed"
    assert _advanced_delivery_status("failed", "sent") == "failed"
    assert _advanced_delivery_status("failed", "delivered") == "delivered"
    assert _advanced_delivery_status("delivered", "failed") == "delivered"
    assert _advanced_delivery_status("read", "failed") == "read"
    assert _advanced_delivery_status("delivered", "read") == "read"


@pytest.mark.asyncio
async def test_infobip_messages_api_uses_approved_whatsapp_template(monkeypatch) -> None:
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"messages": [{"messageId": "msg-1"}]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    monkeypatch.setattr("app.services.infobip.httpx.AsyncClient", Client)
    from app.services.infobip import send_infobip_message

    values = (
        "Anna Muster",
        "12.00 EUR",
        "Schulausflug",
        "https://pay.example/p/abc",
        "ZM-ABC123",
        "Max Lehrer",
    )
    content = CanonicalMessage(
        subject="Schulausflug",
        text="Rendered canonical text",
        payment_link_included=True,
        payment_qr_requested=True,
        payment_qr_url="https://pay.example/api/v1/public/payments/token/qr.png",
        payment_qr_payload="BCD\n002\n1\nSCT",
        language="de",
        whatsapp_template_values=values,
    )
    result = await send_infobip_message(
        authorization="App test",
        base_url="https://example.api.infobip.com",
        channel="whatsapp",
        sender="123",
        recipient="456",
        content=content,
        callback_data="cb",
        webhook_url="https://zahlmeister.example/webhook",
    )
    assert result == "msg-1"
    payload = calls[0][1]["json"]["messages"][0]
    assert payload["template"] == {
        "templateName": INFOBIP_WHATSAPP_TEMPLATE_NAME,
        "language": "de",
    }
    assert payload["content"]["body"] == {
        "type": "TEXT",
        "1": values[0],
        "2": values[1],
        "3": values[2],
        "4": values[3],
        "5": values[4],
        "6": values[5],
    }
    assert "webhooks" not in payload
    assert "options" not in payload


@pytest.mark.asyncio
async def test_infobip_whatsapp_rejects_unapproved_custom_message(monkeypatch) -> None:
    from app.services.infobip import send_infobip_message

    content = CanonicalMessage(
        subject="Custom",
        text="A custom message",
        payment_link_included=True,
        payment_qr_requested=False,
    )
    with pytest.raises(ValueError, match="protected Zahlmeister payment-request template"):
        await send_infobip_message(
            authorization="App test",
            base_url="https://example.api.infobip.com",
            channel="whatsapp",
            sender="123",
            recipient="456",
            content=content,
            callback_data="cb",
        )


@pytest.mark.asyncio
async def test_infobip_subscription_uses_resource_and_basic_auth(monkeypatch) -> None:
    calls = []

    class Response:
        status_code = 201

        def raise_for_status(self):
            return None

    class Session:
        async def flush(self):
            return None

    async def fake_authorization(session, connection):
        return "App test", "https://tenant.api.infobip.com"

    async def fake_request(method, url, authorization, *, json_body=None):
        calls.append((method, url, authorization, json_body))
        return Response()

    monkeypatch.setattr("app.services.infobip.settings.public_app_url", "https://zahlmeister.example")
    monkeypatch.setattr("app.services.infobip.authorization_for_connection", fake_authorization)
    monkeypatch.setattr("app.services.infobip._subscription_request", fake_request)
    connection = SimpleNamespace(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        webhook_key="very-long-random-webhook-key",
        encrypted_config=encrypt_config({}),
        last_error=None,
    )

    assert await ensure_event_subscription(Session(), connection, "whatsapp", "436601234567") is True
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/subscriptions/1/subscription/WHATSAPP")
    payload = calls[0][3]
    assert payload["events"] == ["DELIVERY", "SEEN", "INBOUND_MESSAGE"]
    assert payload["resources"] == ["436601234567"]
    assert payload["profile"]["webhook"]["notifyUrl"].endswith(
        "/api/v1/webhooks/infobip/very-long-random-webhook-key"
    )
    assert payload["profile"]["security"]["type"] == "BASIC"
    stored = decrypt_config(connection.encrypted_config)
    assert stored["subscriptions"]["whatsapp"]["sender"] == "436601234567"


def test_infobip_managed_webhook_requires_matching_basic_auth() -> None:
    key = "some-random-webhook-secret"
    connection = SimpleNamespace(
        webhook_key=key,
        encrypted_config=encrypt_config(
            {"subscriptions": {"whatsapp": {"subscription_id": "sub"}}}
        ),
    )
    encoded = base64.b64encode(f"zahlmeister:{key}".encode()).decode()
    assert verify_webhook_basic_authorization(f"Basic {encoded}", connection) is True
    assert verify_webhook_basic_authorization(None, connection) is False
    wrong = base64.b64encode(b"zahlmeister:wrong").decode()
    assert verify_webhook_basic_authorization(f"Basic {wrong}", connection) is False


@pytest.mark.asyncio
async def test_infobip_email_sends_qr_as_attachment(monkeypatch) -> None:
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"messages": [{"messageId": "mail-1"}]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    monkeypatch.setattr("app.services.infobip.httpx.AsyncClient", Client)
    from app.services.infobip import send_infobip_message

    content = CanonicalMessage(
        subject="Ausflug",
        text="Bitte bezahlen",
        payment_link_included=True,
        payment_qr_requested=True,
        payment_qr_url="https://pay.example/qr.png",
        payment_qr_payload="BCD\n002\n1\nSCT",
    )
    monkeypatch.setattr("app.services.infobip.render_qr_png", lambda payload: b"PNGDATA")
    result = await send_infobip_message(
        authorization="App test",
        base_url="https://example.api.infobip.com",
        channel="email",
        sender="sender@example.test",
        recipient="recipient@example.test",
        content=content,
        callback_data="cb",
        webhook_url=None,
    )
    assert result == "mail-1"
    attachment = calls[0][1]["files"]["attachment"]
    assert attachment[0] == "zahlmeister-payment-qr.png"
    assert attachment[1] == b"PNGDATA"
    assert attachment[2] == "image/png"
