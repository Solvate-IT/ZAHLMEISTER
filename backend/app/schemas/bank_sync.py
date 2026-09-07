from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class BankSyncConnectionRead(BaseModel):
    id: UUID
    provider: str
    status: str
    account_label: str | None = None
    connected_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_tested_at: datetime | None = None
    last_error: str | None = None


class BankSyncStartRead(BaseModel):
    authorization_url: str


class PontoConfigurationRead(BaseModel):
    environment: str
    configured: bool
    redirect_uri: str
    missing: list[str]


class BankSyncAccountRead(BaseModel):
    id: UUID
    external_id: str
    name: str | None = None
    iban: str | None = None
    currency: str | None = None
    enabled: bool
    last_sync_at: datetime | None = None


class BankSyncAccountUpdate(BaseModel):
    enabled: bool


class BankSyncRunRead(BaseModel):
    imported: int
    auto_matched: int
    needs_review: int
    duplicates: int
    synced_at: datetime


class BankSyncTestRead(BaseModel):
    ok: bool
    status: str
    tested_at: datetime
    error: str | None = None
