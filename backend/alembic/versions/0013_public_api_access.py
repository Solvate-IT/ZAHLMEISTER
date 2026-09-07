"""public customer api access

Revision ID: 0013_public_api_access
Revises: 0012_production_operations
Create Date: 2026-09-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_public_api_access"
down_revision: str | None = "0012_production_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    organization_columns = {column["name"] for column in inspector.get_columns("organizations")}
    if "api_enabled" not in organization_columns:
        op.add_column("organizations", sa.Column("api_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.alter_column("organizations", "api_enabled", server_default=None)

    inspector = sa.inspect(bind)
    if "api_credentials" not in inspector.get_table_names():
        op.create_table(
            "api_credentials",
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("token_prefix", sa.String(length=20), nullable=False),
            sa.Column("scopes_json", sa.Text(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True)),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_api_credentials_token_hash"),
        )
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("api_credentials")}
    if "ix_api_credentials_token_hash" not in indexes:
        op.create_index("ix_api_credentials_token_hash", "api_credentials", ["token_hash"], unique=True)
    if "ix_api_credentials_revoked_at" not in indexes:
        op.create_index("ix_api_credentials_revoked_at", "api_credentials", ["revoked_at"])
    if "ix_api_credentials_org_created" not in indexes:
        op.create_index("ix_api_credentials_org_created", "api_credentials", ["organization_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "api_credentials" in inspector.get_table_names():
        op.drop_table("api_credentials")
    inspector = sa.inspect(bind)
    if "organizations" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("organizations")}
        if "api_enabled" in columns:
            op.drop_column("organizations", "api_enabled")
