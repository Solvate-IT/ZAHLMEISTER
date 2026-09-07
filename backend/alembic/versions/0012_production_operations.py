"""production operations heartbeat

Revision ID: 0012_production_operations
Revises: 0011_payment_message_options
Create Date: 2026-09-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_production_operations"
down_revision: str | None = "0011_payment_message_options"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_heartbeats",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_index(
        "ix_runtime_heartbeats_last_seen_at",
        "runtime_heartbeats",
        ["last_seen_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_heartbeats_last_seen_at", table_name="runtime_heartbeats")
    op.drop_table("runtime_heartbeats")
