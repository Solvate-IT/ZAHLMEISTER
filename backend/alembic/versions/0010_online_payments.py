"""provider-neutral online payments

Revision ID: 0010_online_payments
Revises: 0009_integrations
Create Date: 2026-09-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_online_payments"
down_revision: str | None = "0009_integrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "online_payment_connections",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="connecting"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("account_label", sa.String(length=320)),
        sa.Column("profile_id", sa.String(length=120)),
        sa.Column("encrypted_config", sa.Text()),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "provider", name="uq_online_payment_connection_org_provider"
        ),
    )
    op.create_index("ix_online_payment_connections_status", "online_payment_connections", ["status"])
    op.create_index(
        "ix_online_payment_connections_org_provider",
        "online_payment_connections",
        ["organization_id", "provider"],
    )

    op.create_table(
        "online_payment_attempts",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=200)),
        sa.Column("webhook_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="creating"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("checkout_url", sa.Text()),
        sa.Column("payment_method", sa.String(length=80)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["collection_participant_id"], ["collection_participants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["online_payment_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_online_payment_attempts_external_id", "online_payment_attempts", ["external_id"])
    op.create_index("ix_online_payment_attempts_webhook_key", "online_payment_attempts", ["webhook_key"], unique=True)
    op.create_index("ix_online_payment_attempts_status", "online_payment_attempts", ["status"])
    op.create_index(
        "ix_online_payment_attempts_participant_created",
        "online_payment_attempts",
        ["collection_participant_id", "created_at"],
    )
    op.create_index(
        "ix_online_payment_attempts_connection_external",
        "online_payment_attempts",
        ["connection_id", "external_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_online_payment_attempts_connection_external", table_name="online_payment_attempts")
    op.drop_index("ix_online_payment_attempts_participant_created", table_name="online_payment_attempts")
    op.drop_index("ix_online_payment_attempts_status", table_name="online_payment_attempts")
    op.drop_index("ix_online_payment_attempts_webhook_key", table_name="online_payment_attempts")
    op.drop_index("ix_online_payment_attempts_external_id", table_name="online_payment_attempts")
    op.drop_table("online_payment_attempts")
    op.drop_index("ix_online_payment_connections_org_provider", table_name="online_payment_connections")
    op.drop_index("ix_online_payment_connections_status", table_name="online_payment_connections")
    op.drop_table("online_payment_connections")
