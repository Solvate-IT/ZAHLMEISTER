"""participant message locale preference

Revision ID: 0017_participant_locale
Revises: 0016_collection_channel_override
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_participant_locale"
down_revision: str | None = "0016_collection_channel_override"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUPPORTED = (
    "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu",
    "ga", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "participant_preferences" in set(inspector.get_table_names()):
        return
    allowed = ",".join(f"'{language}'" for language in _SUPPORTED)
    op.create_table(
        "participant_preferences",
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.CheckConstraint(f"locale IN ({allowed})", name="ck_participant_preferences_locale"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("participant_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "participant_preferences" in set(inspector.get_table_names()):
        op.drop_table("participant_preferences")
