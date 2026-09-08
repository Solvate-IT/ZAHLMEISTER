"""Adopt the current Zahlmeister schema as the Alembic baseline.

Revision ID: 0001_current_schema_baseline
Revises:
Create Date: 2026-09-08
"""
from collections.abc import Sequence

from alembic import op

from app import models  # noqa: F401
from app.models.base import Base

revision: str = "0001_current_schema_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One-time compatibility baseline: existing installations predate Alembic.
    # create_all creates only missing current tables/indexes and does not rewrite
    # populated tables. Every schema change after this revision must be explicit.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # Never drop an adopted production schema as part of the baseline downgrade.
    pass
