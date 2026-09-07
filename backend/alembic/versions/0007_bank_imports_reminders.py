"""bank imports and reminder rules

Revision ID: 0007_bank_imports_reminders
Revises: 0006_infobip_connections
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_bank_imports_reminders"
down_revision: str | None = "0006_infobip_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "collections",
        sa.Column(
            "reminder_rules_json",
            sa.Text(),
            nullable=False,
            server_default='[{"type":"after_send","days":5}]',
        ),
    )

    op.create_table(
        "bank_statement_imports",
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("format", sa.String(length=30), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unmatched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bank_imports_org_created",
        "bank_statement_imports",
        ["organization_id", "created_at"],
    )

    op.create_table(
        "bank_transactions",
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("counterparty_name", sa.String(length=300), nullable=True),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("bank_transaction_id", sa.String(length=300), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="unmatched"),
        sa.Column("match_confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("match_reason", sa.String(length=200), nullable=True),
        sa.Column("raw_details", sa.Text(), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "candidate_collection_participant_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("applied_payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_id"], ["bank_statement_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_collection_participant_id"],
            ["collection_participants.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["applied_payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "fingerprint",
            name="uq_bank_transaction_org_fingerprint",
        ),
    )
    op.create_index("ix_bank_transactions_booked_at", "bank_transactions", ["booked_at"])
    op.create_index("ix_bank_transactions_status", "bank_transactions", ["status"])
    op.create_index(
        "ix_bank_transactions_import_status",
        "bank_transactions",
        ["import_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_bank_transactions_import_status", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_status", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_booked_at", table_name="bank_transactions")
    op.drop_table("bank_transactions")
    op.drop_index("ix_bank_imports_org_created", table_name="bank_statement_imports")
    op.drop_table("bank_statement_imports")
    op.drop_column("collections", "reminder_rules_json")
