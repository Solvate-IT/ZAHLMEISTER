import pytest
from pydantic import ValidationError

from app.schemas.communications import CommunicationConnectionUpdate
from app.services.infobip import sign_oauth_state, verify_oauth_state
from app.services.message_renderer import CanonicalMessage


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
async def test_infobip_messages_api_sends_qr_as_image(monkeypatch) -> None:
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

    content = CanonicalMessage(
        subject="Ausflug",
        text="Bitte bezahlen",
        payment_link_included=True,
        payment_qr_requested=True,
        payment_qr_url="https://pay.example/api/v1/public/payments/token/qr.png",
        payment_qr_payload="BCD\n002\n1\nSCT",
    )
    result = await send_infobip_message(
        authorization="App test",
        base_url="https://example.api.infobip.com",
        channel="whatsapp",
        sender="123",
        recipient="456",
        content=content,
        callback_data="cb",
        webhook_url=None,
    )
    assert result == "msg-1"
    payload = calls[0][1]["json"]["messages"][0]
    assert payload["content"]["body"]["type"] == "IMAGE"
    assert payload["content"]["body"]["url"].endswith("/qr.png")
    assert payload["content"]["body"]["text"] == "Bitte bezahlen"
    assert payload["options"]["adaptationMode"] is True


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
