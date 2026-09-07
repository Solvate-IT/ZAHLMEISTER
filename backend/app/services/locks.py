from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def transaction_lock(session: AsyncSession, scope: str, key: object) -> None:
    """Serialize one logical resource inside the current PostgreSQL transaction."""
    lock_key = f"zahlmeister:{scope}:{key}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(lock_key))))
