"""communication hub

Revision ID: 0004_communication_hub
Revises: 0003_payment_delivery
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_communication_hub"
down_revision = "0003_payment_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communication_channel_settings",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="external"),
        sa.Column("provider", sa.String(length=40)),
        sa.Column("encrypted_config", sa.Text()),
        sa.Column("sync_cursor", sa.String(length=200)),
        sa.Column("webhook_key", sa.String(length=80)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "channel", name="uq_comm_channel_org_channel"),
    )
    op.create_index("ix_comm_channel_settings_org", "communication_channel_settings", ["organization_id"])
    op.create_index("ix_communication_channel_settings_webhook_key", "communication_channel_settings", ["webhook_key"], unique=True)

    op.add_column("collections", sa.Column("communication_channel", sa.String(length=30), nullable=False, server_default="email"))
    op.add_column("collections", sa.Column("communication_mode", sa.String(length=20), nullable=False, server_default="internal"))
    op.alter_column("collections", "communication_channel", server_default=None)
    op.alter_column("collections", "communication_mode", server_default=None)

    op.add_column("communication_messages", sa.Column("delivery_mode", sa.String(length=20), nullable=False, server_default="internal"))
    op.add_column("communication_messages", sa.Column("direction", sa.String(length=20), nullable=False, server_default="outgoing"))
    op.add_column("communication_messages", sa.Column("sender", sa.String(length=320)))
    op.add_column("communication_messages", sa.Column("subject", sa.String(length=500)))
    op.add_column("communication_messages", sa.Column("body", sa.Text()))
    op.add_column("communication_messages", sa.Column("provider", sa.String(length=40)))
    op.add_column("communication_messages", sa.Column("external_id", sa.String(length=500)))
    op.add_column("communication_messages", sa.Column("in_reply_to", sa.String(length=500)))
    op.add_column("communication_messages", sa.Column("received_at", sa.DateTime(timezone=True)))
    op.add_column("communication_messages", sa.Column("metadata_json", sa.Text()))
    op.create_index("ix_communication_messages_external_id", "communication_messages", ["external_id"])
    op.create_index("ix_communication_messages_in_reply_to", "communication_messages", ["in_reply_to"])
    op.alter_column("communication_messages", "delivery_mode", server_default=None)
    op.alter_column("communication_messages", "direction", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_communication_messages_in_reply_to", table_name="communication_messages")
    op.drop_index("ix_communication_messages_external_id", table_name="communication_messages")
    for column in ["metadata_json", "received_at", "in_reply_to", "external_id", "provider", "body", "subject", "sender", "direction", "delivery_mode"]:
        op.drop_column("communication_messages", column)
    op.drop_column("collections", "communication_mode")
    op.drop_column("collections", "communication_channel")
    op.drop_index("ix_communication_channel_settings_webhook_key", table_name="communication_channel_settings")
    op.drop_index("ix_comm_channel_settings_org", table_name="communication_channel_settings")
    op.drop_table("communication_channel_settings")
