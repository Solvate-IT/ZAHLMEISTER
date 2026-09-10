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


class PlatformCustomerUserRead(BaseModel):
    id: str
    email: str
    display_name: str
    is_active: bool
    email_verified: bool
    created_at: datetime
    last_login_at: datetime | None = None


class PlatformSubscriptionRead(BaseModel):
    id: str
    provider: str
    product_id: str
    status: str
    external_reference: str | None = None
    purchased_at: datetime | None = None
    expires_at: datetime | None = None
    cancelled_at: datetime | None = None
    auto_renew: bool | None = None
    environment: str | None = None
    last_verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PlatformCustomerDetailRead(PlatformCustomerRead):
    users: list[PlatformCustomerUserRead]
    subscriptions: list[PlatformSubscriptionRead]


class PlatformCustomerUpdate(BaseModel):
    organization_name: str | None = Field(default=None, min_length=1, max_length=200)
    api_enabled: bool | None = None


class PlatformGrantProRequest(BaseModel):
    expires_at: datetime | None = None


class PlatformSupportSessionCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class PlatformSupportSessionRead(BaseModel):
    access_token: str
    expires_in: int
    expires_at: datetime
    user_id: str
    user_name: str
    user_email: str
    organization_id: str
    organization_name: str
    read_only: bool = True
