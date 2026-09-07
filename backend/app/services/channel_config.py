SUPPORTED_CHANNELS = (
    "email",
    "sms",
    "whatsapp",
    "telegram",
    "instagram",
    "messenger",
)

INFOBIP_CHANNELS = {
    "email",
    "sms",
    "whatsapp",
    "telegram",
    "instagram",
    "messenger",
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
        if channel != "email" or not config:
            return False
        return all(str(config.get(key) or "").strip() for key in REQUIRED_SMTP_IMAP_FIELDS)
    if provider == "infobip":
        # Every outbound Infobip channel needs a configured sender/resource.
        # Telegram is reply-only in Infobip Conversations; a configured resource still
        # identifies the channel for inbound/reply traffic.
        return connection_active and bool((sender or "").strip())
    return False
