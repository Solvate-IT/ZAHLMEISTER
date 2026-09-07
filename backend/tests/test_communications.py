from app.services.communications import external_launch_uri, normalize_phone


def test_external_mail_sms_whatsapp_uris_are_prefilled() -> None:
    mail, mail_select = external_launch_uri(
        "email", "anna@example.test", "Ausflug", "Bitte zahlen"
    )
    sms, sms_select = external_launch_uri("sms", "+43 660 123", None, "Bitte zahlen")
    whatsapp, whatsapp_select = external_launch_uri(
        "whatsapp", "+43 660 123", None, "Bitte zahlen"
    )
    assert mail.startswith("mailto:anna%40example.test?")
    assert "subject=Ausflug" in mail
    assert sms.startswith("sms:%2B43%20660%20123?body=")
    assert whatsapp.startswith("https://wa.me/43660123?text=")
    assert not mail_select and not sms_select and not whatsapp_select


def test_social_external_fallback_can_require_recipient_selection() -> None:
    telegram, select_telegram = external_launch_uri(
        "telegram", None, None, "Bitte zahlen"
    )
    instagram, select_instagram = external_launch_uri(
        "instagram", None, None, "Bitte zahlen"
    )
    assert telegram.startswith("https://t.me/share/url")
    assert select_telegram
    assert instagram == "https://www.instagram.com/direct/inbox/"
    assert select_instagram


def test_phone_normalization() -> None:
    assert normalize_phone("+43 (660) 12-34") == "+436601234"
    assert normalize_phone(None) == ""


def test_transport_requests_cannot_override_canonical_message() -> None:
    from pydantic import ValidationError

    from app.schemas.communications import ExternalDraftRequest, InternalMessageRequest

    for request_type in (ExternalDraftRequest, InternalMessageRequest):
        try:
            request_type(channel="email", body="provider-specific text")
        except ValidationError:
            pass
        else:
            raise AssertionError("Transport request accepted a message body override")
