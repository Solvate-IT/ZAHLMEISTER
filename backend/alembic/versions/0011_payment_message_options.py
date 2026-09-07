"""payment message link and QR options

Revision ID: 0011_payment_message_options
Revises: 0010_online_payments
Create Date: 2026-09-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_payment_message_options"
down_revision: str | None = "0010_online_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "message_include_payment_link",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "message_include_payment_qr",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "collections",
        sa.Column("message_include_payment_link", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "collections",
        sa.Column("message_include_payment_qr", sa.Boolean(), nullable=True),
    )
    op.alter_column("organizations", "message_include_payment_link", server_default=None)
    op.alter_column("organizations", "message_include_payment_qr", server_default=None)


def downgrade() -> None:
    op.drop_column("collections", "message_include_payment_qr")
    op.drop_column("collections", "message_include_payment_link")
    op.drop_column("organizations", "message_include_payment_qr")
    op.drop_column("organizations", "message_include_payment_link")
