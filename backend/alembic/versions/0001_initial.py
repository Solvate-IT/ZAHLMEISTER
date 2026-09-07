"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "users",
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "participant_lists",
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_participant_lists_org_name",
        "participant_lists",
        ["organization_id", "name"],
        unique=False,
    )

    op.create_table(
        "participants",
        sa.Column("list_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["list_id"], ["participant_lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_participants_list_name", "participants", ["list_id", "name"], unique=False)

    op.create_table(
        "collections",
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("participant_list_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["participant_list_id"], ["participant_lists.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collections_status", "collections", ["status"], unique=False)
    op.create_index(
        "ix_collections_org_created", "collections", ["organization_id", "created_at"], unique=False
    )

    op.create_table(
        "collection_participants",
        sa.Column("collection_id", UUID, nullable=False),
        sa.Column("participant_id", UUID, nullable=False),
        sa.Column("payment_reference", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_reference"),
    )
    op.create_index(
        "ix_collection_participants_status", "collection_participants", ["status"], unique=False
    )
    op.create_index(
        "ix_collection_participants_collection_status",
        "collection_participants",
        ["collection_id", "status"],
        unique=False,
    )

    op.create_table(
        "payments",
        sa.Column("collection_participant_id", UUID, nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("method", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("external_reference", sa.String(length=200), nullable=True),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["collection_participant_id"], ["collection_participants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payments_external_reference", "payments", ["external_reference"], unique=False
    )

    op.create_table(
        "scheduled_jobs",
        sa.Column("organization_id", UUID, nullable=True),
        sa.Column("job_type", sa.String(length=60), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_jobs_status", "scheduled_jobs", ["status"], unique=False)
    op.create_index(
        "ix_scheduled_jobs_scheduled_at", "scheduled_jobs", ["scheduled_at"], unique=False
    )
    op.create_index("ix_jobs_due", "scheduled_jobs", ["status", "scheduled_at"], unique=False)


def downgrade() -> None:
    op.drop_table("scheduled_jobs")
    op.drop_table("payments")
    op.drop_table("collection_participants")
    op.drop_table("collections")
    op.drop_table("participants")
    op.drop_table("participant_lists")
    op.drop_table("users")
    op.drop_table("organizations")
