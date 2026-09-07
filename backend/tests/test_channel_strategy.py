from uuid import uuid4

from app.models.channel_strategy import ParticipantChannelSetting
from app.models.entities import Participant
from app.services import central_mail
from app.services.channel_strategy import (
    ChannelRuntime,
    default_availability,
    effective_availability,
    resolve_channel,
)


def _participant(*, email="anna@example.test", phone="+43 664 1234567", telegram=""):
    addresses = f'{{"telegram":"{telegram}"}}' if telegram else "{}"
    return Participant(
        list_id=uuid4(),
        name="Anna Muster",
        email=email,
        phone=phone,
        channel_addresses_json=addresses,
    )


def _runtime(channel: str, mode: str = "external", configured: bool = True) -> ChannelRuntime:
    return ChannelRuntime(
        channel=channel,
        mode=mode,
        provider=None,
        connection_id=None,
        sender=None,
        config={},
        configured=configured,
    )


def test_default_channel_availability_is_derived_without_rows() -> None:
    participant = _participant(telegram="annam")
    assert default_availability(participant, "email") == "available"
    assert default_availability(participant, "sms") == "available"
    assert default_availability(participant, "whatsapp") == "unknown"
    assert default_availability(participant, "telegram") == "available"


def test_unknown_whatsapp_is_selected_before_email() -> None:
    participant = _participant()
    route = resolve_channel(
        participant,
        order=["whatsapp", "email", "sms", "telegram"],
        runtimes={
            "whatsapp": _runtime("whatsapp"),
            "email": _runtime("email"),
            "sms": _runtime("sms"),
            "telegram": _runtime("telegram", "disabled", False),
        },
    )
    assert route is not None
    assert route.channel == "whatsapp"
    assert route.availability == "unknown"


def test_learned_unavailable_whatsapp_falls_back_to_email() -> None:
    participant = _participant()
    override = ParticipantChannelSetting(
        participant_id=uuid4(),
        channel="whatsapp",
        availability="unavailable",
        enabled=True,
    )
    route = resolve_channel(
        participant,
        order=["whatsapp", "email", "sms", "telegram"],
        runtimes={
            "whatsapp": _runtime("whatsapp"),
            "email": _runtime("email"),
            "sms": _runtime("sms"),
            "telegram": _runtime("telegram", "disabled", False),
        },
        overrides={"whatsapp": override},
    )
    assert route is not None
    assert route.channel == "email"


def test_disabled_participant_channel_is_skipped() -> None:
    participant = _participant()
    override = ParticipantChannelSetting(
        participant_id=uuid4(),
        channel="email",
        availability="available",
        enabled=False,
    )
    assert effective_availability(participant, "email", override) == "unavailable"


def test_desktop_external_capabilities_can_skip_sms() -> None:
    participant = _participant(email=None)
    route = resolve_channel(
        participant,
        order=["sms", "whatsapp", "email", "telegram"],
        runtimes={
            "sms": _runtime("sms"),
            "whatsapp": _runtime("whatsapp"),
            "email": _runtime("email"),
            "telegram": _runtime("telegram", "disabled", False),
        },
        external_channels={"email", "whatsapp", "telegram"},
    )
    assert route is not None
    assert route.channel == "whatsapp"


def test_disabled_organization_channel_is_skipped() -> None:
    participant = _participant()
    route = resolve_channel(
        participant,
        order=["whatsapp", "email", "sms", "telegram"],
        runtimes={
            "whatsapp": _runtime("whatsapp", "disabled", False),
            "email": _runtime("email"),
            "sms": _runtime("sms"),
            "telegram": _runtime("telegram", "disabled", False),
        },
    )
    assert route is not None
    assert route.channel == "email"


def test_reply_address_roundtrip_and_tamper_rejection(monkeypatch) -> None:
    monkeypatch.setattr(central_mail.settings, "app_secret", "test-secret-which-is-long-enough")
    monkeypatch.setattr(central_mail.settings, "mail_reply_domain", "reply.example.test")
    message_id = uuid4()
    address = central_mail.reply_address(message_id)
    assert central_mail.message_id_from_reply_address(address) == message_id
    assert address.startswith("reply+")
    assert str(message_id) not in address

    local, domain = address.split("@", 1)
    replacement = "a" if local[-1] != "a" else "b"
    tampered = f"{local[:-1]}{replacement}@{domain}"
    assert central_mail.message_id_from_reply_address(tampered) is None
