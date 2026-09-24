from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.routes import collections as collection_routes
from app.models.entities import Participant
from app.schemas.communications import DispatchPreviewRequest
from app.services.channel_strategy import ChannelRuntime


@pytest.mark.asyncio
async def test_preview_respects_priority_and_disabled_channels_without_writing(monkeypatch) -> None:
    organization = SimpleNamespace(
        id=uuid4(),
        bank_account_name="Zahlmeister",
        bank_iban="AT611904300234573201",
        message_include_payment_link=True,
        message_include_payment_qr=False,
    )
    collection = SimpleNamespace(
        id=uuid4(),
        status="draft",
        communication_channel="auto",
        message_include_payment_link=None,
        message_include_payment_qr=None,
    )
    participant = Participant(
        list_id=uuid4(),
        name="Anna",
        email="anna@example.test",
        phone="+436601234567",
        channel_addresses_json='{"telegram":"annam"}',
    )
    participant.id = uuid4()
    cp = SimpleNamespace(id=uuid4())

    class Session:
        async def execute(self, statement):
            assert "status =" in str(statement)
            return SimpleNamespace(all=lambda: [(cp, participant)])

        def add(self, _value):
            raise AssertionError("Preview must not create messages")

    async def owned(*_args):
        return collection

    async def order(*_args):
        return ["telegram", "whatsapp", "email", "sms"]

    async def runtimes(*_args):
        return {
            name: ChannelRuntime(name, mode, None, None, None, {}, mode != "disabled")
            for name, mode in [
                ("email", "internal"),
                ("whatsapp", "external"),
                ("sms", "external"),
                ("telegram", "disabled"),
            ]
        }

    async def empty(*_args):
        return {}

    async def render(*_args, **_kwargs):
        return SimpleNamespace(subject="Test subject", text="Hello Anna")

    monkeypatch.setattr(collection_routes, "_owned_collection", owned)
    monkeypatch.setattr(collection_routes, "get_channel_order", order)
    monkeypatch.setattr(collection_routes, "load_channel_runtimes", runtimes)
    monkeypatch.setattr(collection_routes, "load_participant_channel_settings", empty)
    monkeypatch.setattr(collection_routes, "load_participant_locales", empty)
    monkeypatch.setattr(collection_routes, "render_collection_message", render)

    result = await collection_routes.preview_collection_dispatch(
        collection.id,
        DispatchPreviewRequest(external_channels=["email", "whatsapp"]),
        organization,
        Session(),
    )

    assert not result.unreachable
    assert len(result.routes) == 1
    assert result.routes[0].channel == "whatsapp"
    assert result.routes[0].launch_uri.startswith("https://wa.me/436601234567?text=Hello%20Anna")
