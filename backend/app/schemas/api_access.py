from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

API_SCOPES = {
    "participants:read",
    "participants:write",
    "collections:read",
    "collections:write",
    "payments:read",
}


class ApiEnabledUpdate(BaseModel):
    enabled: bool


class ApiSettingsRead(BaseModel):
    enabled: bool
    available_scopes: list[str]


class ApiCredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=20)
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            raise ValueError("Name must not be empty")
        return cleaned

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        normalized = sorted(set(value))
        invalid = [scope for scope in normalized if scope not in API_SCOPES]
        if invalid:
            raise ValueError(f"Unsupported API scopes: {', '.join(invalid)}")
        return normalized


class ApiCredentialRead(BaseModel):
    id: UUID
    name: str
    token_prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiCredentialCreated(ApiCredentialRead):
    token: str


class ExternalCollectionStatus(BaseModel):
    id: UUID
    name: str
    currency: str
    amount: str
    participant_count: int
    paid_count: int
    open_count: int
    paid_amount: str
    total_amount: str
    status: str
