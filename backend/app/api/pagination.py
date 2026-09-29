"""Offset pagination for list endpoints.

``?limit=`` (default DEFAULT_PAGE_SIZE, at most MAX_PAGE_SIZE) and ``?offset=``;
the total number of rows is returned in the ``X-Total-Count`` header, so clients
can page without a change to the response body (which stays a plain list).
"""
from dataclasses import dataclass

from fastapi import Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 1000
TOTAL_COUNT_HEADER = "X-Total-Count"


@dataclass(frozen=True)
class Page:
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    def apply(self, statement: Select) -> Select:
        return statement.limit(self.limit).offset(self.offset)


def page_params(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
) -> Page:
    return Page(limit=limit, offset=offset)


async def total_count(session: AsyncSession, statement: Select) -> int:
    """Rows the (unpaged, unordered) statement returns."""
    counted = statement.order_by(None).limit(None).offset(None).subquery()
    return int(await session.scalar(select(func.count()).select_from(counted)) or 0)


def set_total_count(response: Response, total: int) -> None:
    response.headers[TOTAL_COUNT_HEADER] = str(total)
