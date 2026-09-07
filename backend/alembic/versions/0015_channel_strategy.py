"""channel strategy and participant channel knowledge

Revision ID: 0015_channel_strategy
Revises: 0014_platform_subscriptions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_channel_strategy"
down_revision: str | None = "0014_platform_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_names(inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def _unique_names(inspector, table: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_unique_constraints(table) if constraint.get("name")}


def _check_names(inspector, table: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_check_constraints(table) if constraint.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "communication_preferences" not in tables:
        op.create_table(
            "communication_preferences",
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "channel_order_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'["email","whatsapp","sms","telegram"]'"),
            ),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("organization_id"),
        )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "participant_channel_settings" not in tables:
        op.create_table(
            "participant_channel_settings",
            sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("channel", sa.String(length=30), nullable=False),
            sa.Column("availability", sa.String(length=20), nullable=False, server_default="unknown"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_failure_reason", sa.Text(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint(
                "channel IN ('email','sms','whatsapp','telegram')",
                name="ck_participant_channel_settings_channel",
            ),
            sa.CheckConstraint(
                "availability IN ('unknown','available','unavailable')",
                name="ck_participant_channel_settings_availability",
            ),
            sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "participant_id",
                "channel",
                name="uq_participant_channel_setting_participant_channel",
            ),
        )

    inspector = sa.inspect(bind)
    if "participant_channel_settings" in set(inspector.get_table_names()):
        indexes = _index_names(inspector, "participant_channel_settings")
        if "ix_participant_channel_settings_participant" not in indexes:
            op.create_index(
                "ix_participant_channel_settings_participant",
                "participant_channel_settings",
                ["participant_id"],
                unique=False,
            )
        uniques = _unique_names(inspector, "participant_channel_settings")
        if "uq_participant_channel_setting_participant_channel" not in uniques:
            op.create_unique_constraint(
                "uq_participant_channel_setting_participant_channel",
                "participant_channel_settings",
                ["participant_id", "channel"],
            )
        checks = _check_names(inspector, "participant_channel_settings")
        if "ck_participant_channel_settings_channel" not in checks:
            op.create_check_constraint(
                "ck_participant_channel_settings_channel",
                "participant_channel_settings",
                "channel IN ('email','sms','whatsapp','telegram')",
            )
        if "ck_participant_channel_settings_availability" not in checks:
            op.create_check_constraint(
                "ck_participant_channel_settings_availability",
                "participant_channel_settings",
                "availability IN ('unknown','available','unavailable')",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "participant_channel_settings" in tables:
        op.drop_table("participant_channel_settings")
    inspector = sa.inspect(bind)
    if "communication_preferences" in set(inspector.get_table_names()):
        op.drop_table("communication_preferences")
