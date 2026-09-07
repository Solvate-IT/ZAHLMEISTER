"""explicit collection channel override

Revision ID: 0016_collection_channel_override
Revises: 0015_channel_strategy
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_collection_channel_override"
down_revision: str | None = "0015_channel_strategy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check_names(inspector, table: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table)
        if constraint.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "collections" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("collections")}
    if {"communication_channel", "communication_mode"}.issubset(columns):
        # Since the automatic strategy was introduced, these legacy values have been
        # ignored by runtime code and exposed as auto. Preserve that effective behavior
        # before the fields become meaningful explicit overrides again.
        op.execute(
            sa.text(
                "UPDATE collections "
                "SET communication_channel = 'auto', communication_mode = 'auto' "
                "WHERE communication_channel <> 'auto' OR communication_mode <> 'auto'"
            )
        )

    inspector = sa.inspect(bind)
    checks = _check_names(inspector, "collections")
    if "ck_collections_communication_channel" not in checks:
        op.create_check_constraint(
            "ck_collections_communication_channel",
            "collections",
            "communication_channel IN ('auto','email','whatsapp','sms','telegram')",
        )
    if "ck_collections_communication_mode" not in checks:
        op.create_check_constraint(
            "ck_collections_communication_mode",
            "collections",
            "communication_mode = 'auto'",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "collections" not in set(inspector.get_table_names()):
        return
    checks = _check_names(inspector, "collections")
    if "ck_collections_communication_mode" in checks:
        op.drop_constraint(
            "ck_collections_communication_mode", "collections", type_="check"
        )
    if "ck_collections_communication_channel" in checks:
        op.drop_constraint(
            "ck_collections_communication_channel", "collections", type_="check"
        )
