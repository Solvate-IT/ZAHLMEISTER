from types import SimpleNamespace

import pytest
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api import pagination
from app.api.routes import participant_lists
from app.models.entities import ParticipantList


def test_page_applies_limit_and_offset() -> None:
    statement = pagination.Page(limit=50, offset=100).apply(select(ParticipantList.id))
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "LIMIT 50 OFFSET 100" in sql


@pytest.mark.asyncio
async def test_list_reports_the_total_and_returns_one_page() -> None:
    executed = []

    class Session:
        async def scalar(self, statement):
            executed.append(statement)
            return 1234

        async def execute(self, statement):
            executed.append(statement)
            return SimpleNamespace(all=lambda: [])

    response = Response()
    result = await participant_lists.list_participant_lists(
        response=response,
        page=pagination.Page(limit=10, offset=20),
        organization=SimpleNamespace(id="org"),
        session=Session(),
    )
    assert result == []
    assert response.headers[pagination.TOTAL_COUNT_HEADER] == "1234"
    page_sql = str(executed[-1].compile(dialect=postgresql.dialect()))
    assert "LIMIT" in page_sql and "OFFSET" in page_sql
