from __future__ import annotations

import asyncio

from app import models  # noqa: F401
from app.db.session import engine
from app.models.base import Base


async def create_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def main() -> None:
    try:
        await create_schema()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
