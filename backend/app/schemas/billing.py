from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
