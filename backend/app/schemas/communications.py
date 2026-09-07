from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Channel = Literal["email", "sms", "whatsapp", "telegram"]
DeliveryMode = Literal["internal", "external", "disabled"]
InternalProvider = Literal["zahlmeister_email", "infobip", "smtp_imap", "microsoft365"]


class CommunicationConnectionRead(BaseModel):
    id: UUID
    provider: str
    auth_type: str
    status: str
    account_label: str | None = None
    account_key: str | None = None
    base_url: str | None = None
    connected_at: datetime | None = None
    last_error: str | None = None
    last_tested_at: datetime | None = None


class CommunicationConnectionUpdate(BaseModel):
    account_label: str | None = Field(default=None, max_length=320)
    base_url: str | None = Field(default=None, max_length=500)

    @field_validator("base_url")
    @classmethod
    def clean_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("Infobip base URL must use HTTPS")
        host = (urlparse(value).hostname or "").lower()
        if host != "api.infobip.com" and not host.endswith(".api.infobip.com"):
            raise ValueError("Infobip base URL must use an Infobip API hostname")
        return value


class InfobipConnectRequest(BaseModel):
    base_url: str = Field(default="https://api.infobip.com", max_length=500)
    api_key: str = Field(min_length=8, max_length=1000)
    account_label: str | None = Field(default=None, max_length=320)

    @field_validator("base_url")
    @classmethod
    def clean_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("Infobip base URL must use HTTPS")
        host = (urlparse(value).hostname or "").lower()
        if host != "api.infobip.com" and not host.endswith(".api.infobip.com"):
            raise ValueError("Infobip base URL must use an Infobip API hostname")
        return value


class InfobipOAuthStartRead(BaseModel):
    authorization_url: str


class Microsoft365OAuthStartRead(BaseModel):
    authorization_url: str


class ChannelSettingRead(BaseModel):
    channel: Channel
    mode: DeliveryMode
    provider: str | None = None
    configured: bool = False
    sender: str | None = None
    connection_id: UUID | None = None
    fields: dict[str, str | int | bool | None] = Field(default_factory=dict)
    webhook_url: str | None = None
    supports_internal: bool = True
    status: str = "not_tested"
    last_tested_at: datetime | None = None
    last_error: str | None = None


class ChannelSettingUpdate(BaseModel):
    mode: DeliveryMode
    provider: str | None = Field(default=None, max_length=40)
    connection_id: UUID | None = None
    sender: str | None = Field(default=None, max_length=320)
    fields: dict[str, str | int | bool | None] = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def clean_provider(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else None

    @field_validator("sender")
    @classmethod
    def clean_sender(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        return value or None

    @model_validator(mode="after")
    def normalize_legacy_platform_mail(self) -> "ChannelSettingUpdate":
        # Older clients selected the central Zahlmeister mail server as smtp_imap
        # with an empty tenant configuration. Store the explicit provider now.
        if self.mode == "internal" and self.provider == "smtp_imap" and not self.fields:
            self.provider = "zahlmeister_email"
        return self


class CommunicationPreferencesRead(BaseModel):
    channel_order: list[Channel]


class CommunicationPreferencesUpdate(BaseModel):
    channel_order: list[Channel] = Field(min_length=4, max_length=4)


class CommunicationRead(BaseModel):
    id: UUID
    kind: str
    channel: str
    delivery_mode: str
    direction: str
    sender: str | None
    recipient: str | None
    subject: str | None
    body: str | None
    status: str
    provider: str | None
    sent_at: datetime | None
    received_at: datetime | None
    created_at: datetime
    error: str | None = None


class ExternalDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Channel
    kind: Literal["initial", "reminder", "manual"] = "manual"


class ExternalDraftRead(BaseModel):
    message_id: UUID
    channel: Channel
    recipient: str | None
    subject: str | None
    body: str
    launch_uri: str
    recipient_selection_required: bool = False
    payment_qr_url: str | None = None
    payment_qr_filename: str | None = None


class ExternalOpenedRequest(BaseModel):
    message_id: UUID


class ExternalResultRequest(BaseModel):
    message_id: UUID
    result: Literal["sent", "unavailable", "skipped"]


class InternalMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Channel
    kind: Literal["initial", "reminder", "manual"] = "manual"


class QueueMessageResult(BaseModel):
    message_id: UUID
    status: str


class ChannelFeedbackRequest(BaseModel):
    availability: Literal["unknown", "available", "unavailable"]
    failure_reason: str | None = Field(default=None, max_length=1000)


class DispatchRequest(BaseModel):
    kind: Literal["initial", "reminder", "manual"] = "initial"
    external_channels: list[Channel] = Field(default_factory=list)
    collection_participant_ids: list[UUID] | None = Field(default=None, max_length=1000)
    channel_override: Channel | None = None


class DispatchExternalItem(BaseModel):
    collection_participant_id: UUID
    participant_id: UUID
    name: str
    channel: Channel


class DispatchResult(BaseModel):
    queued_internal: int = 0
    external: list[DispatchExternalItem] = Field(default_factory=list)
    unreachable: list[UUID] = Field(default_factory=list)


class ConnectionTestRead(BaseModel):
    ok: bool
    status: str
    tested_at: datetime
    details: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
