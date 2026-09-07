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
_TABLE = "participant_preferences"
_CHECK = "ck_participant_preferences_locale"


def _allowed_sql() -> str:
    return ",".join(f"'{language}'" for language in _SUPPORTED)


def _validate_existing_table(inspector) -> None:
    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if not {"participant_id", "locale"}.issubset(columns):
        raise RuntimeError(
            "Existing participant_preferences table is missing required columns"
        )

    primary_key = inspector.get_pk_constraint(_TABLE).get("constrained_columns") or []
    if primary_key != ["participant_id"]:
        raise RuntimeError(
            "Existing participant_preferences table has an incompatible primary key"
        )

    foreign_keys = inspector.get_foreign_keys(_TABLE)
    participant_fk = next(
        (
            key
            for key in foreign_keys
            if key.get("constrained_columns") == ["participant_id"]
            and key.get("referred_table") == "participants"
            and key.get("referred_columns") == ["id"]
        ),
        None,
    )
    if participant_fk is None:
        raise RuntimeError(
            "Existing participant_preferences table is missing the participant foreign key"
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    allowed = _allowed_sql()

    if _TABLE not in tables:
        op.create_table(
            _TABLE,
            sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("locale", sa.String(length=10), nullable=False),
            sa.CheckConstraint(f"locale IN ({allowed})", name=_CHECK),
            sa.ForeignKeyConstraint(
                ["participant_id"], ["participants.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("participant_id"),
        )
        return

    _validate_existing_table(inspector)
    checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints(_TABLE)
        if constraint.get("name")
    }
    if _CHECK not in checks:
        invalid = bind.execute(
            sa.text(
                f"SELECT count(*) FROM {_TABLE} "
                f"WHERE locale NOT IN ({allowed})"
            )
        ).scalar_one()
        if invalid:
            raise RuntimeError(
                "Existing participant locale data contains unsupported language codes"
            )
        op.create_check_constraint(_CHECK, _TABLE, f"locale IN ({allowed})")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE in set(inspector.get_table_names()):
        op.drop_table(_TABLE)
