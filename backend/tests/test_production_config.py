from pathlib import Path

from app.core.config import Settings


def test_secret_file_overrides_environment_value(tmp_path: Path) -> None:
    secret_file = tmp_path / "app_secret"
    secret_file.write_text("x" * 48, encoding="utf-8")
    settings = Settings(
        _env_file=None,
        app_secret="unsafe",
        app_secret_file=str(secret_file),
    )
    assert settings.app_secret == "x" * 48


def test_production_security_detects_development_credentials() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        app_secret="short",
        database_url="postgresql+asyncpg://zahlmeister:zahlmeister@db:5432/zahlmeister",
    )
    errors = settings.production_security_errors()
    assert "APP_SECRET is not production-safe" in errors
    assert "DATABASE_URL uses development credentials" in errors


def test_production_security_rejects_unsafe_public_configuration() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        app_secret="x" * 48,
        database_url="postgresql+asyncpg://zahlmeister:secure-password@db:5432/zahlmeister",
        public_app_url="http://app.example.com",
        CORS_ORIGINS="*,http://app.example.com/path",
        mail_delivery_mode="console",
        smtp_host="",
        mail_from_address="noreply@example.com",
        smtp_starttls=False,
        contact_recipient="invalid",
    )
    errors = settings.production_security_errors()
    assert "PUBLIC_APP_URL must be an absolute HTTPS URL" in errors
    assert "CORS_ORIGINS must not contain wildcard origins" in errors
    assert "CORS origin is not a valid HTTPS origin: http://app.example.com/path" in errors
    assert "MAIL_DELIVERY_MODE must be smtp in production" in errors
    assert "Platform SMTP is not fully configured" in errors
    assert "SMTP_STARTTLS must be enabled in production" in errors
    assert "CONTACT_RECIPIENT is invalid" in errors


def test_production_security_accepts_safe_configuration() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        app_secret="x" * 48,
        database_url="postgresql+asyncpg://zahlmeister:secure-password@db:5432/zahlmeister",
        public_app_url="https://app.example.com",
        oauth_callback_base_url="https://app.example.com",
        CORS_ORIGINS="https://app.example.com",
        mail_delivery_mode="smtp",
        smtp_host="smtp.example.com",
        mail_from_address="noreply@example.com",
        smtp_starttls=True,
        platform_imap_host="imap.example.com",
        platform_imap_username="reply@example.com",
        platform_imap_password="secret",
        contact_recipient="support@example.com",
    )
    assert settings.production_security_errors() == []


def test_production_security_rejects_incomplete_mollie_connect_configuration() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        app_secret="x" * 48,
        database_url="postgresql+asyncpg://zahlmeister:secure-password@db:5432/zahlmeister",
        public_app_url="https://app.example.com",
        oauth_callback_base_url="https://app.example.com",
        CORS_ORIGINS="https://app.example.com",
        mail_delivery_mode="smtp",
        smtp_host="smtp.example.com",
        mail_from_address="noreply@example.com",
        platform_imap_host="imap.example.com",
        platform_imap_username="reply@example.com",
        platform_imap_password="secret",
        contact_recipient="support@example.com",
        mollie_oauth_client_id="app_test",
        mollie_oauth_client_secret="",
        mollie_connect_access_token="advanced_test",
    )
    assert "Mollie Connect OAuth configuration is incomplete" in settings.production_security_errors()


def test_production_config_accepts_capacitor_local_origins() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        app_secret="x" * 48,
        database_url="postgresql+asyncpg://zahlmeister:secure-password@db:5432/zahlmeister",
        public_app_url="https://app.example.com",
        oauth_callback_base_url="https://app.example.com",
        CORS_ORIGINS="https://app.example.com,capacitor://localhost,https://localhost",
        mail_delivery_mode="smtp",
        smtp_host="smtp.example.com",
        mail_from_address="noreply@example.com",
        platform_imap_host="imap.example.com",
        platform_imap_username="reply@example.com",
        platform_imap_password="secret",
        contact_recipient="support@example.com",
    )
    errors = settings.production_security_errors()
    assert not any(
        error.startswith("CORS origin is not a valid HTTPS origin") for error in errors
    )
