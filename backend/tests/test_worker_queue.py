"""Worker behaviour: claiming, delivery state and failure handling."""
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app import worker
from app.models.entities import Collection, CollectionParticipant, CommunicationMessage, Organization, ScheduledJob
from app.services import jobs
from app.services.retry import PermanentError, RetryableError


class FakeSession:
    """Just enough of AsyncSession for the worker's transactions."""

    def __init__(self, store: dict, log: list):
        self.store = store
        self.log = log
        self.executed: list = []

    async def get(self, model, key, with_for_update=False):
        return self.store.get((model, key))

    async def execute(self, statement):
        self.executed.append(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    async def scalar(self, statement):
        self.executed.append(statement)
        return None

    def add(self, value):
        self.log.append(("add", value))


class FakeSessionFactory:
    def __init__(self, store: dict):
        self.store = store
        self.log: list = []
        self.sessions: list[FakeSession] = []

    def _context(self):
        factory = self

        class Context:
            async def __aenter__(self_inner):
                session = FakeSession(factory.store, factory.log)
                factory.sessions.append(session)
                factory.log.append("begin")
                return session

            async def __aexit__(self_inner, exc_type, exc, tb):
                factory.log.append("rollback" if exc_type else "commit")
                return False

        return Context()

    def begin(self):
        return self._context()

    def __call__(self):
        return self._context()


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_claim_orders_by_priority_and_caps_jobs_per_organization(monkeypatch) -> None:
    factory = FakeSessionFactory({})
    monkeypatch.setattr(worker, "SessionLocal", factory)
    assert await worker.claim_job() is None
    sql = _sql(factory.sessions[0].executed[0])
    assert "ORDER BY scheduled_jobs.priority, scheduled_jobs.scheduled_at" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    # Organizations that already fill their slots are excluded from the claim.
    assert "NOT IN (SELECT scheduled_jobs.organization_id" in sql
    assert "HAVING count(*) >=" in sql


def test_test_messages_outrank_bulk_deliveries() -> None:
    assert jobs.PRIORITY_INTERACTIVE < jobs.PRIORITY_CONTROL < jobs.PRIORITY_SYNC < jobs.PRIORITY_BULK
    bulk = jobs.message_job(organization_id=uuid4(), collection_id=uuid4(), message_id=uuid4())
    assert bulk.priority == jobs.PRIORITY_BULK
    assert bulk.message_id is not None and bulk.collection_id is not None


@pytest.mark.asyncio
async def test_enqueue_unique_is_idempotent_through_the_partial_unique_index() -> None:
    captured = []

    class Session:
        async def execute(self, statement):
            captured.append(statement)
            return SimpleNamespace(rowcount=0)

    queued = await jobs.enqueue_unique(Session(), job_type=jobs.JOB_SYNC_INBOX, dedupe_key="sync:inbox:1")
    assert queued is False
    sql = _sql(captured[0])
    assert "ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('pending', 'running') DO NOTHING" in sql


def _message(status: str, channel: str) -> CommunicationMessage:
    message = CommunicationMessage(
        organization_id=uuid4(),
        collection_id=uuid4(),
        collection_participant_id=uuid4(),
        kind="initial",
        channel=channel,
        delivery_mode="internal",
        direction="outgoing",
        recipient="ben@example.test" if channel == "email" else "+436601234567",
        subject="Ausflug",
        body="Hallo Ben",
        status=status,
        provider="zahlmeister_email" if channel == "email" else "infobip",
        metadata_json="{}",
    )
    message.id = uuid4()
    return message


def _store_for(message: CommunicationMessage) -> dict:
    cp = CollectionParticipant(status="open", reminder_count=0)
    cp.id = message.collection_participant_id
    collection = Collection(status="active")
    collection.id = message.collection_id
    organization = Organization(name="Verein")
    organization.id = message.organization_id
    return {
        (CommunicationMessage, message.id): message,
        (CollectionParticipant, cp.id): cp,
        (Collection, collection.id): collection,
        (Organization, organization.id): organization,
    }


def _job_for(message: CommunicationMessage) -> ScheduledJob:
    return jobs.message_job(
        organization_id=message.organization_id,
        collection_id=message.collection_id,
        message_id=message.id,
    )


@pytest.mark.asyncio
async def test_interrupted_sms_is_not_repeated_automatically(monkeypatch) -> None:
    message = _message("sending", "sms")
    factory = FakeSessionFactory(_store_for(message))
    monkeypatch.setattr(worker, "SessionLocal", factory)

    async def no_provider(**_kwargs):
        raise AssertionError("an SMS whose outcome is unknown must not be sent again")

    monkeypatch.setattr(worker, "send_infobip_message", no_provider)
    await worker.send_message(_job_for(message))
    assert message.status == "failed"
    assert "not repeated automatically" in message.error


@pytest.mark.asyncio
async def test_interrupted_email_is_resent_with_the_same_message_id(monkeypatch) -> None:
    message = _message("sending", "email")
    factory = FakeSessionFactory(_store_for(message))
    monkeypatch.setattr(worker, "SessionLocal", factory)
    runtime = SimpleNamespace(mode="internal", configured=True, provider="zahlmeister_email", sender="", config={}, connection_id=None)

    async def runtimes(_session, _organization_id):
        return {"email": runtime}

    sent = []

    async def send_smtp_email(**kwargs):
        # The message was committed as "sending" before the provider call.
        assert factory.log[-1] == "commit"
        sent.append(kwargs["message_id"])
        return kwargs["message_id"]

    monkeypatch.setattr(worker, "load_channel_runtimes", runtimes)
    monkeypatch.setattr(worker, "send_smtp_email", send_smtp_email)
    await worker.send_message(_job_for(message))
    assert sent == [f"<zm-{message.id}@zahlmeister>"]
    assert message.status == "sent"


@pytest.mark.asyncio
async def test_queued_message_is_marked_sending_before_the_provider_call(monkeypatch) -> None:
    message = _message("queued", "email")
    factory = FakeSessionFactory(_store_for(message))
    monkeypatch.setattr(worker, "SessionLocal", factory)
    runtime = SimpleNamespace(mode="internal", configured=True, provider="zahlmeister_email", sender="", config={}, connection_id=None)

    async def runtimes(_session, _organization_id):
        return {"email": runtime}

    seen = []

    async def send_smtp_email(**kwargs):
        seen.append(message.status)
        return kwargs["message_id"]

    monkeypatch.setattr(worker, "load_channel_runtimes", runtimes)
    monkeypatch.setattr(worker, "send_smtp_email", send_smtp_email)
    await worker.send_message(_job_for(message))
    assert seen == ["sending"]
    assert message.status == "sent"


@pytest.mark.asyncio
async def test_failed_attempt_returns_message_to_queue_or_fails_it(monkeypatch) -> None:
    for error, expected_job, expected_message in (
        (RetryableError("throttled", retry_after=120), "pending", "queued"),
        (PermanentError("mailbox does not exist"), "failed", "failed"),
    ):
        message = _message("sending", "email")
        job = _job_for(message)
        job.id = uuid4()
        job.attempts = 1
        store = _store_for(message)
        store[(ScheduledJob, job.id)] = job
        factory = FakeSessionFactory(store)
        monkeypatch.setattr(worker, "SessionLocal", factory)
        before = datetime.now(UTC)
        await worker.fail_job(job, error)
        assert job.status == expected_job
        assert message.status == expected_message
        if expected_job == "pending":
            # Retry-After is honoured when it is longer than the backoff.
            assert (job.scheduled_at - before).total_seconds() >= 119


@pytest.mark.asyncio
async def test_scheduled_send_is_blocked_while_email_is_unverified(monkeypatch) -> None:
    collection = Collection(status="scheduled", organization_id=uuid4(), reminder_rules_json="[]")
    collection.id = uuid4()
    factory = FakeSessionFactory({(Collection, collection.id): collection})
    monkeypatch.setattr(worker, "SessionLocal", factory)

    async def unverified(_session, _organization_id):
        return False

    monkeypatch.setattr(worker, "organization_has_verified_member", unverified)
    job = jobs.collection_send_job(
        organization_id=collection.organization_id, collection_id=collection.id, scheduled_at=datetime.now(UTC)
    )
    with pytest.raises(PermanentError):
        await worker.send_collection(job)
    # Not activated: nothing was sent, and the collection still shows as scheduled.
    assert collection.status == "scheduled"
