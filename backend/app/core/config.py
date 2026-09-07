from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SECRET_FIELDS = {
    "app_secret": "app_secret_file",
    "database_url": "database_url_file",
    "smtp_password": "smtp_password_file",
    "platform_imap_password": "platform_imap_password_file",
    "infobip_oauth_client_secret": "infobip_oauth_client_secret_file",
    "microsoft365_client_secret": "microsoft365_client_secret_file",
    "ponto_connect_client_secret": "ponto_connect_client_secret_file",
    "ponto_connect_key_password": "ponto_connect_key_password_file",
    "mollie_oauth_client_secret": "mollie_oauth_client_secret_file",
    "monitoring_token": "monitoring_token_file",
    "platform_admin_bootstrap_password": "platform_admin_bootstrap_password_file",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    app_secret: str = "zahlmeister-development-secret-change-me"
    app_secret_file: str = ""
    database_url: str = "postgresql+asyncpg://zahlmeister:zahlmeister@db:5432/zahlmeister"
    database_url_file: str = ""
    cors_origins_raw: str = Field(default="http://localhost:3003", validation_alias="CORS_ORIGINS")
    public_app_url: str = "http://localhost:3003"
    oauth_callback_base_url: str = ""

    platform_admin_emails_raw: str = Field(default="", validation_alias="PLATFORM_ADMIN_EMAILS")
    platform_admin_bootstrap_email: str = ""
    platform_admin_bootstrap_password: str = ""
    platform_admin_bootstrap_password_file: str = ""
    platform_admin_bootstrap_name: str = "Zahlmeister Administration"

    log_level: str = "INFO"
    log_format: str = "json"
    trust_proxy_headers: bool = True
    readiness_require_worker: bool = False
    worker_heartbeat_seconds: int = 15
    worker_stale_seconds: int = 60
    monitoring_token: str = ""
    monitoring_token_file: str = ""

    job_max_attempts: int = 7
    job_retry_base_seconds: int = 5
    job_retry_max_seconds: int = 900
    job_retry_jitter: float = 0.20
    job_stale_after_seconds: int = 900

    mail_delivery_mode: str = "console"
    mail_from_address: str = "noreply@zahlmeister.local"
    mail_from_name: str = "Zahlmeister"
    mail_reply_domain: str = ""
    contact_recipient: str = "Support@Solvate.at"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_password_file: str = ""
    smtp_starttls: bool = True
    platform_imap_host: str = ""
    platform_imap_port: int = 993
    platform_imap_username: str = ""
    platform_imap_password: str = ""
    platform_imap_password_file: str = ""
    platform_imap_ssl: bool = True
    platform_imap_starttls: bool = False
    platform_imap_folder: str = "INBOX"

    infobip_oauth_client_id: str = ""
    infobip_oauth_client_secret: str = ""
    infobip_oauth_client_secret_file: str = ""
    infobip_oauth_scopes: str = "api_read message:send subscriptions:manage"
    infobip_oauth_authorize_url: str = "https://oneapi.infobip.com/exchange/1/oauth/authorize"
    infobip_oauth_token_url: str = "https://oneapi.infobip.com/exchange/1/oauth/token"
    infobip_default_base_url: str = "https://api.infobip.com"

    microsoft365_client_id: str = ""
    microsoft365_client_secret: str = ""
    microsoft365_client_secret_file: str = ""
    microsoft365_tenant: str = "organizations"
    microsoft365_scopes: str = "openid profile offline_access User.Read Mail.ReadWrite Mail.Send"
    microsoft365_graph_url: str = "https://graph.microsoft.com/v1.0"

    ponto_connect_environment: Literal["sandbox", "live"] = "sandbox"
    ponto_connect_client_id: str = ""
    ponto_connect_client_secret: str = ""
    ponto_connect_client_secret_file: str = ""
    ponto_connect_api_url: str = "https://api.ibanity.com/ponto-connect"
    ponto_connect_authorize_url: str = ""
    ponto_connect_token_url: str = "https://api.ibanity.com/ponto-connect/oauth2/token"
    ponto_connect_scope: str = "offline_access ai name"
    ponto_connect_cert_path: str = ""
    ponto_connect_key_path: str = ""
    ponto_connect_key_password: str = ""
    ponto_connect_key_password_file: str = ""

    mollie_oauth_client_id: str = ""
    mollie_oauth_client_secret: str = ""
    mollie_oauth_client_secret_file: str = ""
    mollie_oauth_authorize_url: str = "https://my.mollie.com/oauth2/authorize"
    mollie_oauth_token_url: str = "https://api.mollie.com/oauth2/tokens"
    mollie_api_url: str = "https://api.mollie.com/v2"
    mollie_oauth_scopes: str = "organizations.read profiles.read payments.read payments.write"
    mollie_test_mode: bool = False

    @model_validator(mode="after")
    def load_file_secrets(self) -> "Settings":
        for value_field, file_field in _SECRET_FIELDS.items():
            path_value = getattr(self, file_field, "").strip()
            if not path_value:
                continue
            path = Path(path_value)
            if not path.is_file():
                raise ValueError(f"Secret file does not exist: {path}")
            value = path.read_text(encoding="utf-8").strip()
            if not value:
                raise ValueError(f"Secret file is empty: {path}")
            setattr(self, value_field, value)
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]

    @property
    def oauth_callback_base(self) -> str:
        return (self.oauth_callback_base_url.strip() or self.public_app_url.strip()).rstrip("/")

    @property
    def ponto_authorization_url(self) -> str:
        if self.ponto_connect_authorize_url.strip():
            return self.ponto_connect_authorize_url.strip()
        if self.ponto_connect_environment == "sandbox":
            return "https://sandbox-authorization.myponto.com/oauth2/auth"
        return "https://authorization.myponto.com/oauth2/auth"

    @property
    def platform_admin_emails(self) -> set[str]:
        return {item.strip().casefold() for item in self.platform_admin_emails_raw.split(",") if item.strip()}

    def production_security_errors(self) -> list[str]:
        if self.environment != "production":
            return []
        errors: list[str] = []
        secret = self.app_secret.strip().lower()
        if (
            len(self.app_secret.strip()) < 32
            or "change-me" in secret
            or "development-secret" in secret
            or "must-be-provided" in secret
        ):
            errors.append("APP_SECRET is not production-safe")
        if "zahlmeister:zahlmeister@" in self.database_url or ":invalid@" in self.database_url:
            errors.append("DATABASE_URL uses development credentials")
        if self.monitoring_token and len(self.monitoring_token) < 24:
            errors.append("MONITORING_TOKEN is too short")
        admin_password = self.platform_admin_bootstrap_password.strip().lower()
        if admin_password and (len(admin_password) < 16 or "change-me" in admin_password):
            errors.append("PLATFORM_ADMIN_BOOTSTRAP_PASSWORD is not production-safe")

        public_url = urlparse(self.public_app_url.strip())
        if public_url.scheme != "https" or not public_url.netloc:
            errors.append("PUBLIC_APP_URL must be an absolute HTTPS URL")
        callback_url = urlparse(self.oauth_callback_base)
        if callback_url.scheme != "https" or not callback_url.netloc:
            errors.append("OAUTH_CALLBACK_BASE_URL must resolve to an absolute HTTPS URL")

        origins = self.cors_origins
        if not origins:
            errors.append("CORS_ORIGINS must not be empty")
        native_origins = {"capacitor://localhost", "ionic://localhost", "http://localhost", "https://localhost"}
        for origin in origins:
            parsed = urlparse(origin)
            if origin == "*":
                errors.append("CORS_ORIGINS must not contain wildcard origins")
                continue
            if origin in native_origins:
                continue
            if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
                errors.append(f"CORS origin is not a valid HTTPS origin: {origin}")

        microsoft_configured = any((self.microsoft365_client_id.strip(), self.microsoft365_client_secret.strip()))
        if microsoft_configured and not (
            self.microsoft365_client_id.strip() and self.microsoft365_client_secret.strip()
        ):
            errors.append("Microsoft 365 OAuth configuration is incomplete")
        graph = urlparse(self.microsoft365_graph_url.strip())
        if microsoft_configured and (graph.scheme != "https" or graph.hostname != "graph.microsoft.com"):
            errors.append("MICROSOFT365_GRAPH_URL must use https://graph.microsoft.com")

        ponto_configured = any(
            (
                self.ponto_connect_client_id.strip(),
                self.ponto_connect_client_secret.strip(),
                self.ponto_connect_cert_path.strip(),
                self.ponto_connect_key_path.strip(),
            )
        )
        if ponto_configured and self.ponto_connect_environment != "live":
            errors.append("PONTO_CONNECT_ENVIRONMENT must be live in production")
        if ponto_configured and "sandbox-authorization.myponto.com" in self.ponto_authorization_url:
            errors.append("Ponto sandbox authorization URL must not be used in production")

        if self.mail_delivery_mode != "smtp":
            errors.append("MAIL_DELIVERY_MODE must be smtp in production")
        if not self.smtp_host.strip() or not self.mail_from_address.strip():
            errors.append("Platform SMTP is not fully configured")
        if not self.smtp_starttls:
            errors.append("SMTP_STARTTLS must be enabled in production")
        if not (
            self.platform_imap_host.strip()
            and self.platform_imap_username.strip()
            and self.platform_imap_password
        ):
            errors.append("Platform reply IMAP is not fully configured")
        if not self.platform_imap_ssl and not self.platform_imap_starttls:
            errors.append("Platform reply IMAP must use SSL/TLS or STARTTLS")
        if self.mail_reply_domain and (
            "." not in self.mail_reply_domain.strip()
            or "@" in self.mail_reply_domain
            or "/" in self.mail_reply_domain
        ):
            errors.append("MAIL_REPLY_DOMAIN is invalid")
        if "@" not in self.contact_recipient or "\n" in self.contact_recipient or "\r" in self.contact_recipient:
            errors.append("CONTACT_RECIPIENT is invalid")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
