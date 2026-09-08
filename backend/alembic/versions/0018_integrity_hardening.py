"""harden default template data integrity

Revision ID: 0018_integrity_hardening
Revises: 0017_participant_locale
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_integrity_hardening"
down_revision: str | None = "0017_participant_locale"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "message_templates"
_INDEX = "uq_message_templates_org_default"


def _existing_index(inspector):
    return next(
        (index for index in inspector.get_indexes(_TABLE) if index.get("name") == _INDEX),
        None,
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    required = {"id", "organization_id", "is_default", "created_at"}
    if not required.issubset(columns):
        missing = ", ".join(sorted(required - columns))
        raise RuntimeError(
            f"Existing {_TABLE} table is missing columns required for integrity hardening: {missing}"
        )

    existing = _existing_index(inspector)
    if existing is not None:
        if not existing.get("unique") or existing.get("column_names") != ["organization_id"]:
            raise RuntimeError(f"Existing {_INDEX} index has an incompatible definition")
        return

    # Older application versions repaired duplicate defaults lazily when templates were
    # opened. Normalize any historical duplicates before the database starts enforcing
    # the invariant. The oldest template remains the default for deterministic behavior.
    bind.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY organization_id
                        ORDER BY created_at ASC, id ASC
                    ) AS position
                FROM message_templates
                WHERE is_default IS TRUE
            )
            UPDATE message_templates AS template
            SET is_default = FALSE
            FROM ranked
            WHERE template.id = ranked.id
              AND ranked.position > 1
            """
        )
    )

    op.create_index(
        _INDEX,
        _TABLE,
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _existing_index(inspector) is not None:
        op.drop_index(_INDEX, table_name=_TABLE)
