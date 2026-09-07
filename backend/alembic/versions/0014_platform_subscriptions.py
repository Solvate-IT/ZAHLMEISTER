"""platform subscriptions and admin audit

Revision ID: 0014_platform_subscriptions
Revises: 0013_public_api_access
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_platform_subscriptions"
down_revision: str | None = "0013_public_api_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_names(inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "store_subscriptions" not in tables:
        op.create_table(
            "store_subscriptions",
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("provider", sa.String(length=20), nullable=False),
            sa.Column("product_id", sa.String(length=200), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("external_reference", sa.String(length=320), nullable=True),
            sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("external_reference"),
            sa.UniqueConstraint("organization_id", "provider", name="uq_store_subscription_org_provider"),
        )

    inspector = sa.inspect(bind)
    subscription_indexes = _index_names(inspector, "store_subscriptions")
    if "ix_store_subscriptions_status" not in subscription_indexes:
        op.create_index("ix_store_subscriptions_status", "store_subscriptions", ["status"], unique=False)
    if "ix_store_subscriptions_expires_at" not in subscription_indexes:
        op.create_index("ix_store_subscriptions_expires_at", "store_subscriptions", ["expires_at"], unique=False)
    if "ix_store_subscriptions_org_status" not in subscription_indexes:
        op.create_index("ix_store_subscriptions_org_status", "store_subscriptions", ["organization_id", "status"], unique=False)

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "platform_admin_audit" not in tables:
        op.create_table(
            "platform_admin_audit",
            sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("details_json", sa.Text(), nullable=False),
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    audit_indexes = _index_names(inspector, "platform_admin_audit")
    if "ix_platform_admin_audit_admin_user_id" not in audit_indexes:
        op.create_index("ix_platform_admin_audit_admin_user_id", "platform_admin_audit", ["admin_user_id"], unique=False)
    if "ix_platform_admin_audit_organization_id" not in audit_indexes:
        op.create_index("ix_platform_admin_audit_organization_id", "platform_admin_audit", ["organization_id"], unique=False)
    if "ix_platform_admin_audit_action" not in audit_indexes:
        op.create_index("ix_platform_admin_audit_action", "platform_admin_audit", ["action"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "platform_admin_audit" in tables:
        indexes = _index_names(inspector, "platform_admin_audit")
        for name in (
            "ix_platform_admin_audit_action",
            "ix_platform_admin_audit_organization_id",
            "ix_platform_admin_audit_admin_user_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="platform_admin_audit")
        op.drop_table("platform_admin_audit")

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "store_subscriptions" in tables:
        indexes = _index_names(inspector, "store_subscriptions")
        for name in (
            "ix_store_subscriptions_org_status",
            "ix_store_subscriptions_expires_at",
            "ix_store_subscriptions_status",
        ):
            if name in indexes:
                op.drop_index(name, table_name="store_subscriptions")
        op.drop_table("store_subscriptions")
