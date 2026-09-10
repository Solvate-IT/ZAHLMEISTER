from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class BillingEntitlementRead(BaseModel):
    plan: Literal["free", "pro"]
    active: bool
    provider: str | None = None
    status: str | None = None
    product_id: str | None = None
    expires_at: datetime | None = None
    auto_renew: bool | None = None


class BillingPurchaseContextRead(BaseModel):
    provider: Literal["apple", "google", "mollie"]
    product_id: str
    account_token: str
    purchase_allowed: bool
    existing_provider: str | None = None
    existing_status: str | None = None
    reason: str | None = None


class GooglePlayBillingConfigRead(BaseModel):
    available: bool
    package_name: str
    product_id: str
    base_plan_id: str


class GooglePlayPurchaseVerifyWrite(BaseModel):
    purchase_token: str = Field(min_length=1, max_length=4096)

    @field_validator("purchase_token")
    @classmethod
    def clean_purchase_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Purchase token must not be empty")
        return value


class MollieBillingConfigRead(BaseModel):
    available: bool
    product_id: str
    amount: str
    currency: str
    interval: str
    environment: Literal["test", "live"]


class MollieBillingCheckoutRead(BaseModel):
    checkout_url: str
    payment_id: str
    resumed: bool


class MollieAutoRenewWrite(BaseModel):
    enabled: bool


class BillingProfileWrite(BaseModel):
    customer_type: Literal["consumer", "business"]
    given_name: str | None = Field(default=None, max_length=120)
    family_name: str | None = Field(default=None, max_length=120)
    organization_name: str | None = Field(default=None, max_length=200)
    billing_email: str = Field(min_length=3, max_length=320)
    street_and_number: str = Field(min_length=2, max_length=240)
    postal_code: str = Field(default="", max_length=40)
    city: str = Field(min_length=1, max_length=160)
    region: str | None = Field(default=None, max_length=160)
    country: str = Field(min_length=2, max_length=2)
    vat_number: str | None = Field(default=None, max_length=40)
    organization_number: str | None = Field(default=None, max_length=80)

    @field_validator(
        "given_name",
        "family_name",
        "organization_name",
        "region",
        "vat_number",
        "organization_number",
    )
    @classmethod
    def clean_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split()).strip()
        return value or None

    @field_validator("billing_email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        value = value.strip()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Invalid billing email")
        return value

    @field_validator("street_and_number", "city")
    @classmethod
    def clean_required(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("Billing field must not be empty")
        return value

    @field_validator("postal_code")
    @classmethod
    def clean_postal_code(cls, value: str) -> str:
        return " ".join(value.split()).strip()

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isalpha() or len(value) != 2:
            raise ValueError("Country must be an ISO 3166-1 alpha-2 code")
        return value

    @model_validator(mode="after")
    def validate_party(self) -> "BillingProfileWrite":
        if self.customer_type == "consumer":
            if not self.given_name or not self.family_name:
                raise ValueError("Consumer billing requires given name and family name")
        else:
            if not self.organization_name:
                raise ValueError("Business billing requires organization name")
            if not self.vat_number and not self.organization_number:
                raise ValueError("Business billing requires a VAT number or organization number")
        return self


class BillingProfileRead(BillingProfileWrite):
    vat_validation_status: str
    vat_validated_at: datetime | None = None


class BillingInvoiceRead(BaseModel):
    id: str
    provider: str
    product_id: str
    tariff_version: str
    period_start: datetime
    period_end: datetime
    gross_amount: str
    currency: str
    vat_rate: str
    vat_scheme: str
    tax_treatment: str
    invoice_number: str | None = None
    status: str
    payment_url: str | None = None
    paid_at: datetime | None = None
