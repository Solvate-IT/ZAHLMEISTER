"""provider-neutral communication connections with Infobip primary provider

Revision ID: 0006_infobip_connections
Revises: 0005_message_templates
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_infobip_connections"
down_revision = "0005_message_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "participants",
        sa.Column("channel_addresses_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.alter_column("participants", "channel_addresses_json", server_default=None)

    op.create_table(
        "communication_connections",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("auth_type", sa.String(length=30), nullable=False, server_default="oauth"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="connected"),
        sa.Column("account_label", sa.String(length=320)),
        sa.Column("account_key", sa.String(length=120)),
        sa.Column("encrypted_config", sa.Text()),
        sa.Column("webhook_key", sa.String(length=80)),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_comm_connections_org_provider",
        "communication_connections",
        ["organization_id", "provider"],
    )
    op.create_index(
        "ix_communication_connections_status",
        "communication_connections",
        ["status"],
    )
    op.create_index(
        "ix_communication_connections_webhook_key",
        "communication_connections",
        ["webhook_key"],
        unique=True,
    )
    op.create_index(
        "ix_communication_connections_account_key",
        "communication_connections",
        ["account_key"],
    )

    op.add_column(
        "communication_channel_settings",
        sa.Column("connection_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "communication_channel_settings",
        sa.Column("sender", sa.String(length=320)),
    )
    op.create_foreign_key(
        "fk_comm_channel_setting_connection",
        "communication_channel_settings",
        "communication_connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_comm_channel_settings_connection",
        "communication_channel_settings",
        ["connection_id"],
    )

    # Direct Twilio/Meta credentials from 0.5/0.6 are intentionally no longer active.
    # Keep the encrypted values for rollback, but switch those channels back to the safe
    # external mode until an Infobip connection is explicitly enabled by the customer.
    op.execute(
        "UPDATE communication_channel_settings "
        "SET mode='external', provider=NULL, connection_id=NULL "
        "WHERE channel IN ('sms', 'whatsapp') AND provider IN ('twilio', 'meta_cloud')"
    )


def downgrade() -> None:
    op.drop_index("ix_comm_channel_settings_connection", table_name="communication_channel_settings")
    op.drop_constraint(
        "fk_comm_channel_setting_connection",
        "communication_channel_settings",
        type_="foreignkey",
    )
    op.drop_column("communication_channel_settings", "sender")
    op.drop_column("communication_channel_settings", "connection_id")
    op.drop_index("ix_communication_connections_account_key", table_name="communication_connections")
    op.drop_index("ix_communication_connections_webhook_key", table_name="communication_connections")
    op.drop_index("ix_communication_connections_status", table_name="communication_connections")
    op.drop_index("ix_comm_connections_org_provider", table_name="communication_connections")
    op.drop_table("communication_connections")
    op.drop_column("participants", "channel_addresses_json")
