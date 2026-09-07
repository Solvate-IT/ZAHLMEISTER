from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ParticipantListCreate(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class ParticipantListUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class ParticipantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    channel_addresses: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("Participant name must not be empty")
        return value

    @field_validator("channel_addresses")
    @classmethod
    def clean_channel_addresses(cls, value: dict[str, str]) -> dict[str, str]:
        telegram = str(value.get("telegram") or "").strip()
        return {"telegram": telegram} if telegram else {}


class ParticipantUpdate(ParticipantCreate):
    pass


class ParticipantChannelRead(BaseModel):
    channel: Literal["email", "whatsapp", "sms", "telegram"]
    enabled: bool
    availability: Literal["unknown", "available", "unavailable"]
    learned: bool = False


class ParticipantChannelUpdate(BaseModel):
    enabled: bool | None = None
    availability: Literal["unknown", "available", "unavailable"] | None = None


class ParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str | None
    phone: str | None
    channel_addresses: dict[str, str] = Field(default_factory=dict)
    channels: list[ParticipantChannelRead] = Field(default_factory=list)


class ParticipantListRead(BaseModel):
    id: UUID
    name: str
    participant_count: int = 0


class ParticipantListDetail(ParticipantListRead):
    participants: list[ParticipantRead]


class ReminderRule(BaseModel):
    type: str = Field(pattern="^(after_send|before_due|on_due|after_due)$")
    days: int = Field(default=0, ge=0, le=365)


class CollectionCreate(BaseModel):
    participant_list_id: UUID
    name: str | None = Field(default=None, max_length=200)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    send_at: datetime | None = None
    due_at: datetime | None = None
    message_template_id: UUID | None = None
    message_body_override: str | None = Field(default=None, max_length=10000)
    reminder_rules: list[ReminderRule] | None = None
    include_payment_link: bool | None = None
    include_payment_qr: bool | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    due_at: datetime | None = None
    include_payment_link: bool | None = None
    include_payment_qr: bool | None = None


class CollectionParticipantRead(BaseModel):
    id: UUID
    participant_id: UUID
    name: str
    email: str | None
    phone: str | None
    payment_reference: str
    payment_url: str
    payment_qr_url: str | None = None
    status: str
    paid_at: datetime | None
    payment_method: str | None = None
    initial_sent_at: datetime | None = None
    last_reminder_at: datetime | None = None
    reminder_count: int = 0
    delivery_status: str | None = None
    delivery_channel: str | None = None
    communication_count: int = 0


class CollectionRead(BaseModel):
    id: UUID
    name: str
    participant_list_id: UUID
    amount: Decimal
    currency: str
    send_at: datetime | None
    due_at: datetime | None
    status: str
    participant_count: int
    paid_count: int
    paid_amount: Decimal
    communication_channel: str = "auto"
    communication_mode: str = "auto"
    channel_order: list[str] = Field(default_factory=list)
    message_template_id: UUID | None = None
    message_body_override: str | None = None
    reminder_rules: list[ReminderRule] = Field(default_factory=list)
    include_payment_link: bool = True
    include_payment_qr: bool = False


class CollectionDetail(CollectionRead):
    participants: list[CollectionParticipantRead]


class PaymentStatusUpdate(BaseModel):
    paid: bool


class QueueActionResult(BaseModel):
    queued: int
