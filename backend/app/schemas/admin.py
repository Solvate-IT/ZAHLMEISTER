from datetime import datetime

from pydantic import BaseModel, Field


class PlatformAdminSummary(BaseModel):
    customers: int
    free_customers: int
    pro_customers: int
    active_users: int


class PlatformCustomerRead(BaseModel):
    organization_id: str
    organization_name: str
    created_at: datetime
    locale: str
    currency: str
    api_enabled: bool
    plan: str
    billing_provider: str | None = None
    subscription_status: str | None = None
    subscription_expires_at: datetime | None = None
    user_count: int
    active_user_count: int
    primary_email: str | None = None
    last_login_at: datetime | None = None
    participant_lists: int
    participants: int
    collections: int


class PlatformCustomerUpdate(BaseModel):
    organization_name: str | None = Field(default=None, min_length=1, max_length=200)
    api_enabled: bool | None = None


class PlatformGrantProRequest(BaseModel):
    expires_at: datetime | None = None
