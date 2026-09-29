"""The PostgreSQL job queue: job types, priorities and enqueue helpers.

Jobs are rows in ``scheduled_jobs``. Workers claim them with
``FOR UPDATE SKIP LOCKED`` (app.worker), so any number of worker processes can
share the queue. Typed columns (``collection_id``, ``message_id``) identify what a
job works on; ``dedupe_key`` makes periodic and rule-based work idempotent.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ScheduledJob

# Lower runs first.
PRIORITY_INTERACTIVE = 10  # a user is waiting for it (test messages)
PRIORITY_CONTROL = 20  # fan-out jobs that queue the individual deliveries
PRIORITY_SYNC = 50  # periodic mailbox, bank and billing syncs
PRIORITY_BULK = 100  # individual deliveries of a collection send

JOB_SEND_COLLECTION = "send_collection"
JOB_SEND_REMINDERS = "send_reminders"
JOB_SEND_MESSAGE = "send_message"
JOB_SYNC_PLATFORM_INBOX = "sync_platform_inbox"
JOB_SYNC_INBOX = "sync_inbox"
JOB_SYNC_BANK_CONNECTION = "sync_bank_connection"
JOB_SYNC_BILLING = "sync_billing"

ACTIVE_STATUSES = ("pending", "running")


def message_job(
    *,
    organization_id: uuid.UUID,
    collection_id: uuid.UUID | None,
    message_id: uuid.UUID,
    priority: int = PRIORITY_BULK,
    scheduled_at: datetime | None = None,
) -> ScheduledJob:
    """The delivery job for one already-rendered communication message."""
    return ScheduledJob(
        organization_id=organization_id,
        job_type=JOB_SEND_MESSAGE,
        payload=json.dumps({"message_id": str(message_id)}),
        priority=priority,
        scheduled_at=scheduled_at or datetime.now(UTC),
        collection_id=collection_id,
        message_id=message_id,
    )


def reminder_dedupe_key(collection_id: uuid.UUID, rule_key: str) -> str:
    return f"reminder:{collection_id}:{rule_key}"


def reminder_job(
    *,
    organization_id: uuid.UUID,
    collection_id: uuid.UUID,
    rule_key: str,
    scheduled_at: datetime,
) -> ScheduledJob:
    return ScheduledJob(
        organization_id=organization_id,
        job_type=JOB_SEND_REMINDERS,
        payload=json.dumps(
            {"collection_id": str(collection_id), "automatic": True, "rule": rule_key}
        ),
        priority=PRIORITY_CONTROL,
        scheduled_at=scheduled_at,
        collection_id=collection_id,
        dedupe_key=reminder_dedupe_key(collection_id, rule_key),
    )


def collection_send_job(
    *, organization_id: uuid.UUID, collection_id: uuid.UUID, scheduled_at: datetime
) -> ScheduledJob:
    return ScheduledJob(
        organization_id=organization_id,
        job_type=JOB_SEND_COLLECTION,
        payload=json.dumps({"collection_id": str(collection_id)}),
        priority=PRIORITY_CONTROL,
        scheduled_at=scheduled_at,
        collection_id=collection_id,
        dedupe_key=f"send_collection:{collection_id}",
    )


async def enqueue_unique(
    session: AsyncSession,
    *,
    job_type: str,
    dedupe_key: str,
    payload: dict[str, Any] | None = None,
    organization_id: uuid.UUID | None = None,
    priority: int = PRIORITY_SYNC,
    scheduled_at: datetime | None = None,
) -> bool:
    """Queue a job unless the same logical work is already pending or running.

    Relies on the partial unique index ``uq_scheduled_jobs_active_dedupe``, so it
    is race-free across processes. Returns True when a job was queued.
    """
    statement = (
        insert(ScheduledJob)
        .values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            job_type=job_type,
            payload=json.dumps(payload or {}),
            status="pending",
            priority=priority,
            scheduled_at=scheduled_at or datetime.now(UTC),
            attempts=0,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(
            index_elements=[ScheduledJob.dedupe_key],
            index_where=text("dedupe_key IS NOT NULL AND status IN ('pending', 'running')"),
        )
    )
    result = await session.execute(statement)
    return bool(result.rowcount)
