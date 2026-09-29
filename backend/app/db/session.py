from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings


def server_settings(*, statement_timeout_ms: int | None = None) -> dict[str, str]:
    """PostgreSQL session settings applied to every pooled connection."""
    return {
        "application_name": "zahlmeister",
        "statement_timeout": str(
            settings.db_statement_timeout_ms if statement_timeout_ms is None else statement_timeout_ms
        ),
        "lock_timeout": str(settings.db_lock_timeout_ms),
        "idle_in_transaction_session_timeout": str(settings.db_idle_in_transaction_timeout_ms),
    }


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    pool_recycle=settings.db_pool_recycle_seconds,
    connect_args={"server_settings": server_settings()},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
