"""payment delivery and receiving bank account

Revision ID: 0003_payment_delivery
Revises: 0002_auth_sessions
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_payment_delivery"
down_revision = "0002_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("bank_account_name", sa.String(length=200)))
    op.add_column("organizations", sa.Column("bank_iban", sa.String(length=34)))
    op.add_column("organizations", sa.Column("bank_bic", sa.String(length=11)))

    op.add_column("collection_participants", sa.Column("public_token", sa.String(length=80)))
    op.execute(
        "UPDATE collection_participants "
        "SET public_token = substr(md5(random()::text || id::text || clock_timestamp()::text), 1, 32) "
        "WHERE public_token IS NULL"
    )
    op.alter_column("collection_participants", "public_token", nullable=False)
    op.create_index(
        "ix_collection_participants_public_token",
        "collection_participants",
        ["public_token"],
        unique=True,
    )
    op.add_column(
        "collection_participants", sa.Column("initial_sent_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "collection_participants", sa.Column("last_reminder_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "collection_participants",
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("collection_participants", "reminder_count", server_default=None)

    op.create_table(
        "communication_messages",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("recipient", sa.String(length=320)),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["collection_participant_id"],
            ["collection_participants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_communication_messages_status", "communication_messages", ["status"], unique=False
    )
    op.create_index(
        "ix_communication_messages_collection_participant",
        "communication_messages",
        ["collection_participant_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("communication_messages")
    op.drop_index("ix_collection_participants_public_token", table_name="collection_participants")
    op.drop_column("collection_participants", "reminder_count")
    op.drop_column("collection_participants", "last_reminder_at")
    op.drop_column("collection_participants", "initial_sent_at")
    op.drop_column("collection_participants", "public_token")
    op.drop_column("organizations", "bank_bic")
    op.drop_column("organizations", "bank_iban")
    op.drop_column("organizations", "bank_account_name")
