"""participant message locale

Revision ID: 0017_participant_locale
Revises: 0016_collection_channel_override
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_participant_locale"
down_revision: str | None = "0016_collection_channel_override"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUPPORTED = (
    "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu",
    "ga", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv",
)


def _check_names(inspector, table: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table)
        if constraint.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "participants" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("participants")}
    if "locale" not in columns:
        op.add_column("participants", sa.Column("locale", sa.String(length=10), nullable=True))

    inspector = sa.inspect(bind)
    checks = _check_names(inspector, "participants")
    if "ck_participants_locale" not in checks:
        allowed = ",".join(f"'{language}'" for language in _SUPPORTED)
        op.create_check_constraint(
            "ck_participants_locale",
            "participants",
            f"locale IS NULL OR locale IN ({allowed})",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "participants" not in set(inspector.get_table_names()):
        return
    checks = _check_names(inspector, "participants")
    if "ck_participants_locale" in checks:
        op.drop_constraint("ck_participants_locale", "participants", type_="check")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("participants")}
    if "locale" in columns:
        op.drop_column("participants", "locale")
