"""integration health and bank sync

Revision ID: 0009_integrations
Revises: 0008_account_lifecycle
Create Date: 2026-09-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_integrations"
down_revision: str | None = "0008_account_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("communication_connections", sa.Column("last_tested_at", sa.DateTime(timezone=True)))
    op.add_column("communication_channel_settings", sa.Column("status", sa.String(length=30), nullable=False, server_default="not_tested"))
    op.add_column("communication_channel_settings", sa.Column("last_tested_at", sa.DateTime(timezone=True)))
    op.add_column("communication_channel_settings", sa.Column("last_error", sa.Text()))
    op.alter_column("communication_channel_settings", "status", server_default=None)

    op.create_table(
        "bank_sync_connections",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="connecting"),
        sa.Column("account_label", sa.String(length=320)),
        sa.Column("encrypted_config", sa.Text()),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_tested_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "provider", name="uq_bank_sync_connection_org_provider"),
    )
    op.create_index("ix_bank_sync_connections_status", "bank_sync_connections", ["status"])
    op.create_index("ix_bank_sync_connections_org_provider", "bank_sync_connections", ["organization_id", "provider"])

    op.create_table(
        "bank_sync_accounts",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=320)),
        sa.Column("iban", sa.String(length=64)),
        sa.Column("currency", sa.String(length=3)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["bank_sync_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "external_id", name="uq_bank_sync_account_external"),
    )
    op.create_index("ix_bank_sync_accounts_org", "bank_sync_accounts", ["organization_id"])

    op.alter_column("bank_transactions", "import_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("bank_transactions", sa.Column("bank_sync_account_id", postgresql.UUID(as_uuid=True)))
    op.add_column("bank_transactions", sa.Column("source_provider", sa.String(length=40)))
    op.create_foreign_key(
        "fk_bank_transactions_sync_account",
        "bank_transactions",
        "bank_sync_accounts",
        ["bank_sync_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_bank_transactions_sync_account", "bank_transactions", ["bank_sync_account_id"])


def downgrade() -> None:
    op.drop_index("ix_bank_transactions_sync_account", table_name="bank_transactions")
    op.drop_constraint("fk_bank_transactions_sync_account", "bank_transactions", type_="foreignkey")
    op.drop_column("bank_transactions", "source_provider")
    op.drop_column("bank_transactions", "bank_sync_account_id")
    op.alter_column("bank_transactions", "import_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_index("ix_bank_sync_accounts_org", table_name="bank_sync_accounts")
    op.drop_table("bank_sync_accounts")
    op.drop_index("ix_bank_sync_connections_org_provider", table_name="bank_sync_connections")
    op.drop_index("ix_bank_sync_connections_status", table_name="bank_sync_connections")
    op.drop_table("bank_sync_connections")
    op.drop_column("communication_channel_settings", "last_error")
    op.drop_column("communication_channel_settings", "last_tested_at")
    op.drop_column("communication_channel_settings", "status")
    op.drop_column("communication_connections", "last_tested_at")
