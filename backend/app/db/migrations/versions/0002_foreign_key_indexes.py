"""Index the foreign keys that hot queries and cascading deletes rely on.

Without these, per-collection message lookups, payment lookups per participant,
the sender-name lookup per organization and every ON DELETE CASCADE/RESTRICT
check scanned the referencing table.

Revision ID: 0002_foreign_key_indexes
Revises: 0001_baseline
Create Date: 2026-09-29
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002_foreign_key_indexes"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    ("bank_transactions", "applied_payment_id"),
    ("bank_transactions", "candidate_collection_participant_id"),
    ("billing_payment_transactions", "organization_id"),
    ("collection_participants", "participant_id"),
    ("collections", "participant_list_id"),
    ("communication_messages", "collection_id"),
    ("communication_messages", "organization_id"),
    ("online_payment_attempts", "organization_id"),
    ("payments", "collection_participant_id"),
    ("scheduled_jobs", "organization_id"),
    ("users", "organization_id"),
)


def upgrade() -> None:
    for table, column in _INDEXES:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column], unique=False)


def downgrade() -> None:
    for table, column in reversed(_INDEXES):
        op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
