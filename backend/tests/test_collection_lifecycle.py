from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.routes.collections import _collection_jobs, can_delete_collection


def test_delete_only_before_any_delivery_or_payment() -> None:
    draft = SimpleNamespace(status="draft")
    scheduled = SimpleNamespace(status="scheduled")
    active = SimpleNamespace(status="active")
    assert can_delete_collection(draft, has_messages=False, has_payments=False, has_attempts=False)
    assert can_delete_collection(
        scheduled, has_messages=False, has_payments=False, has_attempts=False
    )
    assert not can_delete_collection(
        active, has_messages=False, has_payments=False, has_attempts=False
    )
    assert not can_delete_collection(
        draft, has_messages=True, has_payments=False, has_attempts=False
    )
    assert not can_delete_collection(
        draft, has_messages=False, has_payments=True, has_attempts=False
    )
    assert not can_delete_collection(
        draft, has_messages=False, has_payments=False, has_attempts=True
    )


@pytest.mark.asyncio
async def test_collection_job_selection_never_touches_another_collection() -> None:
    collection_id, organization_id = uuid4(), uuid4()
    current = SimpleNamespace(id=collection_id, organization_id=organization_id)
    job = SimpleNamespace(job_type="send_collection", collection_id=collection_id)

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [job]))

    session = Session()
    assert await _collection_jobs(session, current) == [job]

    compiled = session.statement.compile()
    sql = str(compiled)
    # Bound to this collection and organization through the typed, indexed column;
    # no lookup by payload text that could match another collection's jobs.
    assert "scheduled_jobs.collection_id =" in sql
    assert "scheduled_jobs.organization_id =" in sql
    assert "payload" not in sql.split("WHERE", 1)[1]
    params = set(map(str, compiled.params.values()))
    assert {str(collection_id), str(organization_id)} <= params
    assert any(
        isinstance(value, (list, tuple)) and set(value) == {"send_collection", "send_reminders", "send_message"}
        for value in compiled.params.values()
    )
