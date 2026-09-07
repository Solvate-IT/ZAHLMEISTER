from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class OnlinePaymentConnectionRead(BaseModel):
    id: UUID
    provider: str
    status: str
    enabled: bool
    account_label: str | None = None
    profile_id: str | None = None
    connected_at: datetime | None = None
    last_tested_at: datetime | None = None
    last_error: str | None = None


class OnlinePaymentOAuthStartRead(BaseModel):
    authorization_url: str


class OnlinePaymentProfileRead(BaseModel):
    id: str
    name: str
    website: str | None = None
    status: str | None = None
    selected: bool = False


class OnlinePaymentProfileUpdate(BaseModel):
    profile_id: str


class OnlinePaymentEnabledUpdate(BaseModel):
    enabled: bool


class OnlinePaymentTestRead(BaseModel):
    ok: bool
    status: str
    tested_at: datetime
    error: str | None = None


class OnlineCheckoutRead(BaseModel):
    provider: str
    checkout_url: str
    attempt_id: UUID
