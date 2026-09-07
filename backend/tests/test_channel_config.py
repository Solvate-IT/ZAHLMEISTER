from app.services.channel_config import internal_channel_configured


def test_internal_email_smtp_requires_sender_and_smtp_host() -> None:
    assert internal_channel_configured(
        "email",
        provider="smtp_imap",
        config={"from_address": "me@example.test", "smtp_host": "smtp.example.test"},
    )
    assert not internal_channel_configured(
        "email",
        provider="smtp_imap",
        config={"smtp_host": "smtp.example.test"},
    )


def test_infobip_requires_active_connection_and_sender() -> None:
    assert internal_channel_configured(
        "sms",
        provider="infobip",
        connection_active=True,
        sender="InfoSMS",
    )
    assert not internal_channel_configured(
        "sms",
        provider="infobip",
        connection_active=False,
        sender="InfoSMS",
    )
    assert not internal_channel_configured(
        "whatsapp",
        provider="infobip",
        connection_active=True,
        sender=None,
    )


def test_unknown_internal_provider_is_never_configured() -> None:
    assert not internal_channel_configured(
        "sms",
        provider="twilio",
        config={"account_sid": "legacy"},
    )
