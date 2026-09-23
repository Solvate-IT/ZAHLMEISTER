import asyncio

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

import app.models  # noqa: F401
from app.db.session import engine
from app.models.base import Base


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
    # Keep bootstrap safe for existing installations without introducing a separate
    # migration framework. Nullable columns can be added idempotently before the
    # strict drift verification runs.
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


def _verify_schema(connection: Connection) -> None:
    inspector = inspect(connection)
    expected_tables = set(Base.metadata.tables)
    actual_tables = set(inspector.get_table_names())

    missing_tables = sorted(expected_tables - actual_tables)
    unexpected_tables = sorted(actual_tables - expected_tables)
    problems: list[str] = []
    if missing_tables:
        problems.append(f"missing tables: {', '.join(missing_tables)}")
    if unexpected_tables:
        problems.append(f"unexpected tables: {', '.join(unexpected_tables)}")

    for table_name in sorted(expected_tables & actual_tables):
        expected_columns = set(Base.metadata.tables[table_name].columns.keys())
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = sorted(expected_columns - actual_columns)
        unexpected_columns = sorted(actual_columns - expected_columns)
        if missing_columns:
            problems.append(
                f"{table_name}: missing columns: {', '.join(missing_columns)}"
            )
        if unexpected_columns:
            problems.append(
                f"{table_name}: unexpected columns: {', '.join(unexpected_columns)}"
            )

    if problems:
        raise RuntimeError("Database schema drift detected: " + "; ".join(problems))


async def create_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_apply_compatible_schema_updates)
        await connection.run_sync(_verify_schema)


async def main() -> None:
    await create_schema()


if __name__ == "__main__":
    asyncio.run(main())
