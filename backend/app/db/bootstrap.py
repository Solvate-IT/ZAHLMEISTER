import asyncio

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

import app.models  # noqa: F401
from app.db.session import engine
from app.models.base import Base


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
        await connection.run_sync(_verify_schema)


async def main() -> None:
    await create_schema()


if __name__ == "__main__":
    asyncio.run(main())
