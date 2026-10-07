"""Bring the database schema to the current Alembic revision.

``python -m app.db.bootstrap`` is what every environment runs: the compose
``bootstrap`` service, docker/scripts/test.sh (twice, to prove idempotence) and the
production deployment. In one transaction it

1. adopts an installation that predates Alembic (brings it to the baseline shape
   and stamps the baseline revision),
2. applies all pending migrations,
3. verifies that the resulting schema matches the ORM models exactly.

Any failure rolls the whole transaction back, so a deployment either ends on a
verified schema or leaves the database untouched.
"""
import asyncio
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

import app.models  # noqa: F401
from app.db.session import engine
from app.models.base import Base

BASELINE_REVISION = "0001_baseline"
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
# Serializes concurrent bootstrap runs (for example two deploys racing).
_BOOTSTRAP_LOCK_KEY = 7_346_522_110


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


# --- Adoption of installations that predate Alembic ----------------------------
# Runs only once per installation, before the baseline revision is stamped.


def _column_exists(connection: Connection, table_name: str, column_name: str) -> bool:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {
        column["name"] for column in inspector.get_columns(table_name)
    }


def _drop_empty_legacy_column(
    connection: Connection,
    table_name: str,
    column_name: str,
) -> None:
    if not _column_exists(connection, table_name, column_name):
        return
    # Identifiers are internal constants from the call sites below, never user input.
    row = connection.exec_driver_sql(
        f'SELECT 1 FROM "{table_name}" '
        f'WHERE "{column_name}" IS NOT NULL LIMIT 1'
    ).first()
    if row is not None:
        raise RuntimeError(
            f"Refusing to drop non-empty obsolete column: {table_name}.{column_name}"
        )
    connection.exec_driver_sql(
        f'ALTER TABLE "{table_name}" DROP COLUMN "{column_name}"'
    )


def _drop_legacy_communication_mode(connection: Connection) -> None:
    table_name = "collections"
    column_name = "communication_mode"
    if not _column_exists(connection, table_name, column_name):
        return
    unexpected = connection.exec_driver_sql(
        'SELECT 1 FROM "collections" '
        'WHERE "communication_mode" IS NOT NULL '
        'AND "communication_mode" <> \'auto\' LIMIT 1'
    ).first()
    if unexpected is not None:
        raise RuntimeError(
            "Refusing to drop collections.communication_mode because non-auto values exist"
        )
    connection.exec_driver_sql(
        'ALTER TABLE "collections" DROP COLUMN "communication_mode"'
    )


def _apply_compatible_schema_updates(connection: Connection) -> None:
    connection.exec_driver_sql(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(50)"
    )

    # Never discard unexpected production data silently. Legacy columns that were
    # never part of a working feature are removed only when empty; the old collection
    # mode is removed only when it contains its sole historical value ("auto").
    _drop_empty_legacy_column(connection, "users", "terms_accepted_at")
    _drop_empty_legacy_column(connection, "users", "privacy_accepted_at")
    _drop_legacy_communication_mode(connection)
    _drop_empty_legacy_column(
        connection, "communication_channel_settings", "webhook_key"
    )
    _drop_empty_legacy_column(connection, "billing_invoices", "payment_url")

    # These two tables only mirrored the tracked seller configuration. Historical
    # invoices already contain immutable seller snapshots, so no invoice history
    # depends on these mirrors. Refuse deletion if an installation contains data
    # outside the historical Zahlmeister shapes.
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "billing_tax_registrations" in tables:
        unexpected_registration = connection.exec_driver_sql(
            'SELECT 1 FROM "billing_tax_registrations" '
            'WHERE "registration_type" NOT IN (\'vat\', \'eu_oss\') LIMIT 1'
        ).first()
        if unexpected_registration is not None:
            raise RuntimeError(
                "Refusing to drop billing_tax_registrations with unexpected registration types"
            )
        connection.exec_driver_sql("DROP TABLE billing_tax_registrations")
    if "billing_legal_entities" in tables:
        unexpected_entity = connection.exec_driver_sql(
            'SELECT 1 FROM "billing_legal_entities" '
            'WHERE "code" <> \'platform\' LIMIT 1'
        ).first()
        if unexpected_entity is not None:
            raise RuntimeError(
                "Refusing to drop billing_legal_entities with non-platform entities"
            )
        connection.exec_driver_sql("DROP TABLE billing_legal_entities")


# --- Migration and verification ---------------------------------------------------


def schema_drift(connection: Connection) -> list:
    """Differences between the ORM models and the live schema (empty when in sync)."""
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return compare_metadata(context, Base.metadata)


def _migrate(connection: Connection) -> None:
    # Migrations may run longer than the application's statement timeout; lock
    # waits stay bounded so a forgotten session cannot hold the deployment hostage.
    connection.exec_driver_sql("SET LOCAL statement_timeout = 0")
    connection.exec_driver_sql("SET LOCAL lock_timeout = '30s'")
    connection.exec_driver_sql(f"SELECT pg_advisory_xact_lock({_BOOTSTRAP_LOCK_KEY})")

    config = alembic_config(connection)
    tables = set(inspect(connection).get_table_names())
    if "alembic_version" not in tables and tables & set(Base.metadata.tables):
        _apply_compatible_schema_updates(connection)
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")

    drift = schema_drift(connection)
    if drift:
        raise RuntimeError(
            "Database schema does not match the models after migration: "
            + "; ".join(repr(item) for item in drift)
        )


async def create_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(_migrate)


async def main() -> None:
    await create_schema()


if __name__ == "__main__":
    asyncio.run(main())
