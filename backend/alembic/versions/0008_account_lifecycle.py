"""account lifecycle and privacy controls

Revision ID: 0008_account_lifecycle
Revises: 0007_bank_imports_reminders
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_account_lifecycle"
down_revision: str | None = "0007_bank_imports_reminders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("privacy_accepted_at", sa.DateTime(timezone=True)))

    op.create_table(
        "account_action_tokens",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_action_tokens_user_id", "account_action_tokens", ["user_id"])
    op.create_index("ix_account_action_tokens_purpose", "account_action_tokens", ["purpose"])
    op.create_index(
        "ix_account_action_tokens_token_hash", "account_action_tokens", ["token_hash"], unique=True
    )
    op.create_index("ix_account_action_tokens_expires_at", "account_action_tokens", ["expires_at"])
    op.create_index(
        "ix_account_action_tokens_user_purpose",
        "account_action_tokens",
        ["user_id", "purpose"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_action_tokens_user_purpose", table_name="account_action_tokens")
    op.drop_index("ix_account_action_tokens_expires_at", table_name="account_action_tokens")
    op.drop_index("ix_account_action_tokens_token_hash", table_name="account_action_tokens")
    op.drop_index("ix_account_action_tokens_purpose", table_name="account_action_tokens")
    op.drop_index("ix_account_action_tokens_user_id", table_name="account_action_tokens")
    op.drop_table("account_action_tokens")
    op.drop_column("users", "privacy_accepted_at")
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "email_verified_at")
