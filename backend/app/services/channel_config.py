from app.core.config import settings

SUPPORTED_CHANNELS = (
    "email",
    "whatsapp",
    "sms",
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


def canonical_internal_provider(
    channel: str,
    provider: str | None,
    config: dict | None = None,
) -> str | None:
    """Normalize legacy provider values without exposing platform credentials per tenant."""
    if channel == "email" and provider == "smtp_imap" and not config:
        # Older settings used smtp_imap + an empty organization config to mean the
        # central Zahlmeister mail server. Keep those rows backwards compatible,
        # but expose a distinct provider to the runtime from now on.
        return "zahlmeister_email"
    return provider


def internal_channel_configured(
    channel: str,
    *,
    provider: str | None,
    config: dict | None = None,
    connection_active: bool = False,
    sender: str | None = None,
) -> bool:
    provider = canonical_internal_provider(channel, provider, config)
    if provider == "zahlmeister_email":
        return channel == "email" and bool(
            settings.smtp_host.strip() and settings.mail_from_address.strip()
        )
    if provider == "smtp_imap":
        return channel == "email" and bool(config) and all(
            str(config.get(key) or "").strip() for key in REQUIRED_SMTP_IMAP_FIELDS
        )
    if provider == "microsoft365":
        return channel == "email" and connection_active
    if provider == "infobip":
        if channel not in INFOBIP_CHANNELS:
            return False
        return connection_active and bool((sender or "").strip())
    return False
