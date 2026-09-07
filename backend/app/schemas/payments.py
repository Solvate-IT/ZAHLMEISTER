from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.payments import is_valid_bic, is_valid_iban, normalize_bic, normalize_iban


class PaymentSettingsUpdate(BaseModel):
    account_name: str = Field(min_length=1, max_length=200)
    iban: str = Field(min_length=15, max_length=34)
    bic: str | None = Field(default=None, max_length=11)
    include_payment_link: bool = True
    include_payment_qr: bool = False

    @model_validator(mode="after")
    def validate_message_options(self):
        if not self.include_payment_link and not self.include_payment_qr:
            raise ValueError("Enable at least the payment link or the payment QR code")
        return self

    @field_validator("account_name")
    @classmethod
    def clean_account_name(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("Account name is required")
        return value

    @field_validator("iban")
    @classmethod
    def validate_iban(cls, value: str) -> str:
        value = normalize_iban(value)
        if not is_valid_iban(value):
            raise ValueError("Invalid IBAN")
        return value

    @field_validator("bic")
    @classmethod
    def validate_bic(cls, value: str | None) -> str | None:
        value = normalize_bic(value)
        if not is_valid_bic(value):
            raise ValueError("Invalid BIC")
        return value


class PaymentSettingsRead(BaseModel):
    account_name: str | None
    iban: str | None
    bic: str | None
    configured: bool
    include_payment_link: bool = True
    include_payment_qr: bool = False


class PublicPaymentRead(BaseModel):
    collection_name: str
    participant_name: str
    amount: Decimal
    currency: str
    status: str
    paid_at: datetime | None
    account_name: str | None
    iban: str | None
    bic: str | None
    payment_reference: str
    epc_qr_data: str | None
    online_payment_available: bool = False
    online_payment_provider: str | None = None
