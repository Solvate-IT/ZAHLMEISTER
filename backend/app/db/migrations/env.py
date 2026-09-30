"""Alembic environment for the Zahlmeister schema.

Two ways in:
- app.db.bootstrap hands over an open connection (config.attributes["connection"]),
  so adoption, upgrade and the drift check share one transaction;
- the alembic CLI (backend/alembic.ini) connects on its own, for developers who
  create revisions: ``alembic revision --autogenerate -m "..."``.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401
from app.core.config import settings
from app.db.session import server_settings
from app.models.base import Base

config = context.config
target_metadata = Base.metadata
if config.config_file_name is not None and "connection" not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )


def _run_with(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    # Migrations may legitimately run longer than the application's statement
    # timeout (index builds, backfills); lock waits stay bounded.
    engine = create_async_engine(
        settings.database_url,
        poolclass=pool.NullPool,
        connect_args={"server_settings": server_settings(statement_timeout_ms=0)},
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run_with)
    await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with(connection)
    else:
        asyncio.run(_run_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
