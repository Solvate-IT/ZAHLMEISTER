from app.core.config import settings

SUPPORTED_CHANNELS = (
    "email",
    "sms",
    "whatsapp",
    "telegram",
)

INFOBIP_CHANNELS = {
    "email",
    "sms",
    "whatsapp",
}

SECRET_FIELDS = {
    "email": {"smtp_password", "imap_password"},
}

REQUIRED_SMTP_IMAP_FIELDS = {"from_address", "smtp_host"}


def internal_channel_configured(
    channel: str,
    *,
    provider: str | None,
    config: dict | None = None,
    connection_active: bool = False,
    sender: str | None = None,
) -> bool:
    if provider == "smtp_imap":
        if channel != "email":
            return False
        if config and all(
            str(config.get(key) or "").strip() for key in REQUIRED_SMTP_IMAP_FIELDS
        ):
            return True
        return bool(settings.smtp_host.strip() and settings.mail_from_address.strip())
    if provider == "microsoft365":
        return channel == "email" and connection_active
    if provider == "infobip":
        if channel not in INFOBIP_CHANNELS:
            return False
        return connection_active and bool((sender or "").strip())
    return False
