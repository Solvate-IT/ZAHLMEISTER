from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class BankMatchSuggestion(BaseModel):
    collection_participant_id: UUID
    collection_name: str
    participant_name: str
    amount: Decimal
    currency: str
    payment_reference: str


class BankTransactionRead(BaseModel):
    id: UUID
    booked_at: datetime
    amount: Decimal
    currency: str
    counterparty_name: str | None
    reference: str | None
    status: str
    match_confidence: Decimal | None
    match_reason: str | None
    candidate_collection_participant_id: UUID | None
    candidate_collection_name: str | None = None
    candidate_participant_name: str | None = None
    suggestions: list[BankMatchSuggestion] = Field(default_factory=list)


class BankStatementImportRead(BaseModel):
    id: UUID
    filename: str
    format: str
    created_at: datetime
    transaction_count: int
    auto_matched_count: int
    review_count: int
    unmatched_count: int
    duplicate_count: int
    transactions: list[BankTransactionRead] = Field(default_factory=list)


class BankMatchRequest(BaseModel):
    collection_participant_id: UUID


class BankImportListItem(BaseModel):
    id: UUID
    filename: str
    format: str
    created_at: datetime
    transaction_count: int
    auto_matched_count: int
    review_count: int
    unmatched_count: int
    duplicate_count: int
