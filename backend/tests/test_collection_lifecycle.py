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
    collection_id, other_id, message_id = uuid4(), uuid4(), uuid4()
    current = SimpleNamespace(id=collection_id, organization_id=uuid4())
    jobs = [
        SimpleNamespace(job_type="send_collection", payload=f'{{"collection_id":"{collection_id}"}}'),
        SimpleNamespace(job_type="send_reminders", payload=f'{{"collection_id":"{other_id}"}}'),
        SimpleNamespace(job_type="send_message", payload=f'{{"message_id":"{message_id}"}}'),
        SimpleNamespace(job_type="send_message", payload=f'{{"message_id":"{other_id}"}}'),
        SimpleNamespace(job_type="send_message", payload="not json"),
    ]

    class Session:
        calls = 0

        async def execute(self, _statement):
            self.calls += 1
            values = [message_id] if self.calls == 1 else jobs
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: values))

    assert await _collection_jobs(Session(), current) == [jobs[0], jobs[2]]
