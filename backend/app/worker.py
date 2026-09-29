"""Background worker: runs queued jobs and schedules periodic work.

Start one or more processes with ``python -m app.worker``. Each process runs

- ``settings.worker_concurrency`` job slots. A slot claims one due job at a time
  with ``FOR UPDATE SKIP LOCKED``, highest priority first, and never lets a single
  organization occupy more than ``settings.worker_max_jobs_per_organization``
  slots, so one large send cannot hold up everybody else;
- a heartbeat (one ``runtime_heartbeats`` row per process);
- a scheduler. Exactly one scheduler is active across all processes, elected
  through a PostgreSQL advisory lock that is released when its connection ends.
  It enqueues the periodic mailbox, bank and billing syncs as de-duplicated jobs,
  recovers jobs of crashed workers and purges old ones.

SIGTERM stops claiming new work and lets running jobs finish.
"""
import asyncio
import json
import logging
import os
import signal
import socket
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.core.observability import configure_logging
from app.db.session import SessionLocal, engine
from app.models.billing import BillingInvoice
from app.models.entities import (
    BankSyncConnection,
    Collection,
    CollectionParticipant,
    CommunicationChannelSetting,
    CommunicationConnection,
    CommunicationMessage,
    Organization,
    RuntimeHeartbeat,
    ScheduledJob,
)
from app.models.platform import StoreSubscription
from app.services import bank_sync, microsoft365
from app.services.auth import organization_has_verified_member
from app.services.central_mail import (
    message_id_from_reply_address,
    platform_imap_config,
    platform_inbox_configured,
    reply_address,
)
from app.services.channel_strategy import load_channel_runtimes
from app.services.communications import SMTP_POOL, fetch_imap, send_smtp_email
from app.services.infobip import (
    authorization_for_connection,
    connection_is_active,
    connection_webhook_url,
    send_infobip_message,
)
from app.services.jobs import (
    JOB_SEND_COLLECTION,
    JOB_SEND_MESSAGE,
    JOB_SEND_REMINDERS,
    JOB_SYNC_BANK_CONNECTION,
    JOB_SYNC_BILLING,
    JOB_SYNC_INBOX,
    JOB_SYNC_PLATFORM_INBOX,
    PRIORITY_SYNC,
    enqueue_unique,
    reminder_dedupe_key,
    reminder_job,
)
from app.services.message_dispatch import queue_collection_messages
from app.services.message_renderer import canonical_from_stored_message
from app.services.mollie_billing import (
    OPEN_INVOICE_STATUSES,
    billing_configured as mollie_billing_configured,
    sync_subscription as sync_mollie_subscription,
)
from app.services.reminders import deserialize_reminder_rules, reminder_schedule
from app.services.retry import PermanentError, is_retryable_exception, retry_delay_seconds
from app.services.secrets import decrypt_config

configure_logging()
logger = logging.getLogger("zahlmeister.worker")

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
HEARTBEAT_PREFIX = "worker:"
INBOX_SYNC_SECONDS = 60
BANK_SYNC_CHECK_SECONDS = 300
BANK_SYNC_INTERVAL = timedelta(hours=1)
BILLING_SYNC_SECONDS = 600
STALE_RECOVERY_SECONDS = 60
PURGE_SECONDS = 3600
PURGE_BATCH = 5000
SCHEDULER_TICK_SECONDS = 5
SCHEDULER_STANDBY_SECONDS = 15
# Distinct from app.db.bootstrap's key: only one active scheduler across processes.
SCHEDULER_LOCK_KEY = 7_346_522_111


def _heartbeat_name() -> str:
    return f"{HEARTBEAT_PREFIX}{WORKER_ID}"[:80]


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


# --- Queue --------------------------------------------------------------------------


async def claim_job() -> ScheduledJob | None:
    now = datetime.now(UTC)
    # Organizations that already occupy their share of slots wait for later claims.
    saturated = (
        select(ScheduledJob.organization_id)
        .where(ScheduledJob.status == "running", ScheduledJob.organization_id.is_not(None))
        .group_by(ScheduledJob.organization_id)
        .having(func.count() >= settings.worker_max_jobs_per_organization)
    )
    async with SessionLocal.begin() as session:
        stmt = (
            select(ScheduledJob)
            .where(
                ScheduledJob.status == "pending",
                ScheduledJob.scheduled_at <= now,
                or_(
                    ScheduledJob.organization_id.is_(None),
                    ScheduledJob.organization_id.not_in(saturated),
                ),
            )
            .order_by(ScheduledJob.priority, ScheduledJob.scheduled_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = (await session.execute(stmt)).scalar_one_or_none()
        if job is None:
            return None
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.attempts += 1
        await session.flush()
        await session.refresh(job)
        session.expunge(job)
        return job


async def complete_job(job: ScheduledJob) -> None:
    async with SessionLocal.begin() as session:
        stored = await session.get(ScheduledJob, job.id, with_for_update=True)
        if stored:
            stored.status = "done"
            stored.finished_at = datetime.now(UTC)
            stored.last_error = None


def _message_id_of(job: ScheduledJob) -> UUID | None:
    if job.message_id is not None:
        return job.message_id
    try:
        return UUID(json.loads(job.payload)["message_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


async def fail_job(job: ScheduledJob, error: Exception) -> None:
    retryable = is_retryable_exception(error) and job.attempts < settings.job_max_attempts
    delay = retry_delay_seconds(
        job.attempts,
        base_seconds=settings.job_retry_base_seconds,
        max_seconds=settings.job_retry_max_seconds,
        jitter_fraction=settings.job_retry_jitter,
    )
    retry_after = getattr(error, "retry_after", None)
    if isinstance(retry_after, (int, float)) and retry_after > delay:
        delay = float(retry_after)
    async with SessionLocal.begin() as session:
        stored = await session.get(ScheduledJob, job.id, with_for_update=True)
        if not stored:
            return
        stored.status = "pending" if retryable else "failed"
        stored.last_error = str(error)[:2000]
        stored.started_at = None
        if retryable:
            stored.scheduled_at = datetime.now(UTC) + timedelta(seconds=delay)
        else:
            stored.finished_at = datetime.now(UTC)
        if stored.job_type == JOB_SEND_MESSAGE:
            message_id = _message_id_of(stored)
            message = (
                await session.get(CommunicationMessage, message_id, with_for_update=True)
                if message_id is not None
                else None
            )
            if message is not None:
                if retryable and message.status == "sending":
                    # The provider reported a failure, so nothing went out: the next
                    # attempt may send again.
                    message.status = "queued"
                    message.error = stored.last_error
                elif not retryable and message.status not in {"sent", "delivered", "read", "skipped"}:
                    message.status = "failed"
                    message.error = stored.last_error
    logger.warning(
        "Job retry scheduled" if retryable else "Job permanently failed",
        extra={
            "event": "job_retry" if retryable else "job_failed",
            "job_id": str(job.id),
            "job_type": job.job_type,
            "attempt": job.attempts,
            "retry_in_seconds": round(delay, 2) if retryable else None,
            "organization_id": str(job.organization_id) if job.organization_id else None,
        },
    )


async def update_worker_heartbeat(*, scheduler_active: bool = False) -> None:
    now = datetime.now(UTC)
    details = json.dumps(
        {"worker_id": WORKER_ID, "slots": settings.worker_concurrency, "scheduler": scheduler_active}
    )
    async with SessionLocal.begin() as session:
        heartbeat = await session.get(RuntimeHeartbeat, _heartbeat_name(), with_for_update=True)
        if heartbeat is None:
            session.add(RuntimeHeartbeat(name=_heartbeat_name(), last_seen_at=now, details_json=details))
        else:
            heartbeat.last_seen_at = now
            heartbeat.details_json = details


async def recover_stale_jobs() -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.job_stale_after_seconds)
    recovered = 0
    async with SessionLocal.begin() as session:
        rows = (
            await session.execute(
                select(ScheduledJob)
                .where(
                    ScheduledJob.status == "running",
                    ScheduledJob.started_at.is_not(None),
                    ScheduledJob.started_at <= cutoff,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for job in rows:
            job.status = "pending" if job.attempts < settings.job_max_attempts else "failed"
            job.last_error = "Recovered after stale worker execution"
            job.started_at = None
            if job.status == "pending":
                job.scheduled_at = datetime.now(UTC)
            else:
                job.finished_at = datetime.now(UTC)
            recovered += 1
    if recovered:
        logger.warning("Recovered stale jobs", extra={"event": "jobs_recovered", "attempt": recovered})
    return recovered


async def purge_finished_jobs() -> int:
    """Delete finished jobs past retention, in batches so no lock is held for long.

    Failed jobs are kept three times as long: they are what an operator looks at.
    """
    now = datetime.now(UTC)
    retention = timedelta(days=settings.job_retention_days)
    purged = 0
    for statuses, cutoff in (
        (("done", "cancelled"), now - retention),
        (("failed",), now - 3 * retention),
    ):
        while True:
            async with SessionLocal.begin() as session:
                batch = (
                    select(ScheduledJob.id)
                    .where(ScheduledJob.status.in_(statuses), ScheduledJob.finished_at < cutoff)
                    .limit(PURGE_BATCH)
                )
                result = await session.execute(
                    delete(ScheduledJob).where(ScheduledJob.id.in_(batch))
                )
            purged += result.rowcount or 0
            if (result.rowcount or 0) < PURGE_BATCH:
                break
    async with SessionLocal.begin() as session:
        await session.execute(
            delete(RuntimeHeartbeat).where(
                RuntimeHeartbeat.name.like(f"{HEARTBEAT_PREFIX}%"),
                RuntimeHeartbeat.last_seen_at < now - timedelta(days=1),
            )
        )
    if purged:
        logger.info("Purged finished jobs", extra={"event": "jobs_purged", "attempt": purged})
    return purged


# --- Sending --------------------------------------------------------------------------


async def _require_verified_organization(session, organization_id: UUID) -> None:
    if not await organization_has_verified_member(session, organization_id):
        raise PermanentError(
            "The account email address is not verified; scheduled sending stays "
            "paused until it is verified"
        )


async def _queue_message_jobs(collection_id: UUID, *, kind: str) -> int:
    async with SessionLocal.begin() as session:
        collection = await session.get(Collection, collection_id, with_for_update=True)
        if collection is None:
            raise ValueError(f"Collection {collection_id} not found")
        if collection.status == "cancelled":
            return 0
        await _require_verified_organization(session, collection.organization_id)
        organization = await session.get(Organization, collection.organization_id)
        if organization is None or not organization.bank_account_name or not organization.bank_iban:
            raise ValueError("Receiving bank account is not configured")
        outcome = await queue_collection_messages(
            session,
            collection=collection,
            organization=organization,
            kind=kind,
            include_external=False,
        )
        return outcome.queued_internal


def _collection_id_of(job: ScheduledJob) -> UUID:
    return job.collection_id or UUID(json.loads(job.payload)["collection_id"])


async def send_collection(job: ScheduledJob) -> None:
    collection_id = _collection_id_of(job)
    first_activation = False
    send_at = datetime.now(UTC)
    due_at = None
    organization_id = None
    reminder_rules: list[dict] = []
    async with SessionLocal.begin() as session:
        collection = await session.get(Collection, collection_id, with_for_update=True)
        if collection is None:
            raise ValueError(f"Collection {collection_id} not found")
        if collection.status == "cancelled":
            return
        # Checked before activation, so a blocked collection stays "scheduled".
        await _require_verified_organization(session, collection.organization_id)
        first_activation = collection.status != "active"
        collection.status = "active"
        send_at = collection.send_at or datetime.now(UTC)
        due_at = collection.due_at
        organization_id = collection.organization_id
        reminder_rules = deserialize_reminder_rules(collection.reminder_rules_json)

    queued = await _queue_message_jobs(collection_id, kind="initial")
    logger.info("Collection %s activated; %s messages queued", collection_id, queued)
    if first_activation and organization_id:
        schedules = reminder_schedule(
            rules=reminder_rules,
            send_at=send_at,
            due_at=due_at,
            now=datetime.now(UTC),
        )
        if schedules:
            async with SessionLocal.begin() as session:
                for rule_key, scheduled_at in schedules:
                    existing = await session.scalar(
                        select(ScheduledJob.id)
                        .where(
                            ScheduledJob.dedupe_key == reminder_dedupe_key(collection_id, rule_key),
                            ScheduledJob.status.in_(["pending", "running", "done"]),
                        )
                        .limit(1)
                    )
                    if existing is None:
                        session.add(
                            reminder_job(
                                organization_id=organization_id,
                                collection_id=collection_id,
                                rule_key=rule_key,
                                scheduled_at=scheduled_at,
                            )
                        )


async def send_reminders(job: ScheduledJob) -> None:
    collection_id = _collection_id_of(job)
    queued = await _queue_message_jobs(collection_id, kind="reminder")
    logger.info("Collection %s reminder run; %s messages queued", collection_id, queued)


async def send_message(job: ScheduledJob) -> None:
    message_id = _message_id_of(job)
    if message_id is None:
        raise ValueError("Job does not reference a message")
    provider = ""
    sender = ""
    config: dict = {}
    connection_id: UUID | None = None
    recipient = ""
    channel = ""
    organization_name = "Zahlmeister"

    async with SessionLocal.begin() as session:
        message = await session.get(CommunicationMessage, message_id, with_for_update=True)
        if message is None:
            raise ValueError(f"Message {message_id} not found")
        cp = await session.get(CollectionParticipant, message.collection_participant_id, with_for_update=True)
        if cp is None:
            raise ValueError("Collection participant missing")
        if message.status in {"sent", "delivered", "read"}:
            return
        if message.status == "sending" and message.channel != "email":
            # An earlier attempt stopped between the provider call and recording its
            # outcome, so this SMS or WhatsApp message may already have been delivered.
            message.status = "failed"
            message.error = (
                "Delivery was interrupted and its outcome is unknown; it was not "
                "repeated automatically to avoid a duplicate. Resend it if needed."
            )
            return
        # An interrupted email is sent again: it carries the same Message-ID, which
        # lets receiving mail servers discard the duplicate.
        collection = await session.get(Collection, message.collection_id)
        if message.status not in {"queued", "sending"} or (
            message.kind != "test" and (collection is None or collection.status == "cancelled")
        ):
            message.status = "skipped"
            message.error = "Collection cancelled or message no longer queued"
            return
        if message.kind == "reminder" and cp.status != "open":
            message.status = "skipped"
            message.error = "Payment already received"
            return
        if not message.recipient:
            message.status = "skipped"
            message.error = "No recipient"
            return

        content = canonical_from_stored_message(message)
        recipient = message.recipient
        channel = message.channel
        if message.kind == "test" and message.channel == "email" and message.provider == "zahlmeister_email":
            provider = "zahlmeister_email"
            sender = ""
            config = {}
            connection_id = None
        else:
            runtimes = await load_channel_runtimes(session, message.organization_id)
            runtime = runtimes.get(message.channel)
            if runtime is None or runtime.mode != "internal" or not runtime.configured:
                raise ValueError(f"Internal {message.channel} is not configured")
            provider = message.provider or runtime.provider or ""
            sender = runtime.sender or ""
            config = runtime.config
            connection_id = runtime.connection_id
        organization = await session.get(Organization, message.organization_id)
        if organization is not None:
            organization_name = organization.name
        # Committed before the provider is called: if the worker dies before the
        # outcome is stored, the next attempt knows the message may have gone out.
        message.status = "sending"
        message_kind = message.kind

    message_header_id = f"<zm-{message_id}@zahlmeister>"
    if provider == "zahlmeister_email":
        external_id = await send_smtp_email(
            recipient=recipient,
            content=content,
            config={
                **config,
                "from_name": organization_name,
                **({} if message_kind == "test" else {"reply_to": reply_address(message_id)}),
            },
            message_id=message_header_id,
        )
    elif provider == "smtp_imap":
        external_id = await send_smtp_email(
            recipient=recipient,
            content=content,
            config=config,
            message_id=message_header_id,
        )
    elif provider == "microsoft365":
        if connection_id is None:
            raise ValueError("Microsoft 365 connection missing")
        external_id = await microsoft365.send_email(
            connection_id=connection_id,
            recipient=recipient,
            content=content,
        )
    elif provider == "infobip":
        if connection_id is None:
            raise ValueError("Infobip connection missing")
        async with SessionLocal.begin() as session:
            connection = await session.get(CommunicationConnection, connection_id)
            if not connection_is_active(connection):
                raise ValueError("Infobip connection is not active")
            assert connection is not None
            authorization, base_url = await authorization_for_connection(session, connection)
            webhook_url = connection_webhook_url(connection.webhook_key) if connection.webhook_key else None
        external_id = await send_infobip_message(
            authorization=authorization,
            base_url=base_url,
            channel=channel,
            sender=sender,
            recipient=recipient,
            content=content,
            callback_data=str(message_id),
            webhook_url=webhook_url,
        )
    else:
        raise ValueError(f"Unsupported internal provider: {provider}")

    now = datetime.now(UTC)
    async with SessionLocal.begin() as session:
        stored = await session.get(CommunicationMessage, message_id, with_for_update=True)
        if stored is None:
            return
        cp = await session.get(CollectionParticipant, stored.collection_participant_id, with_for_update=True)
        if cp is None:
            raise ValueError("Collection participant missing")
        stored.status = "sent"
        stored.sent_at = now
        stored.external_id = external_id or message_header_id
        stored.provider = provider
        stored.error = None
        if stored.kind == "initial":
            cp.initial_sent_at = cp.initial_sent_at or now
        elif stored.kind == "reminder":
            cp.last_reminder_at = now
            cp.reminder_count += 1


# --- Mailbox sync -----------------------------------------------------------------------


async def _store_incoming_email(
    channel_setting: CommunicationChannelSetting,
    *,
    provider: str,
    candidates: list[str],
    external_id: str | None,
    in_reply_to: str | None,
    sender: str | None,
    recipient: str | None,
    subject: str | None,
    body: str,
    received_at: datetime,
) -> None:
    candidates = [item for item in candidates if item]
    if not candidates:
        return
    async with SessionLocal.begin() as session:
        parent = await session.scalar(
            select(CommunicationMessage)
            .where(
                CommunicationMessage.organization_id == channel_setting.organization_id,
                CommunicationMessage.direction == "outgoing",
                CommunicationMessage.channel == "email",
                CommunicationMessage.provider == provider,
                CommunicationMessage.external_id.in_(candidates),
            )
            .order_by(CommunicationMessage.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if parent is None:
            return
        if external_id:
            duplicate = await session.scalar(
                select(CommunicationMessage.id).where(
                    CommunicationMessage.organization_id == channel_setting.organization_id,
                    CommunicationMessage.external_id == external_id,
                    CommunicationMessage.direction == "incoming",
                )
            )
            if duplicate is not None:
                return
        session.add(
            CommunicationMessage(
                organization_id=parent.organization_id,
                collection_id=parent.collection_id,
                collection_participant_id=parent.collection_participant_id,
                kind="reply",
                channel="email",
                delivery_mode="internal",
                direction="incoming",
                sender=sender,
                recipient=recipient,
                subject=subject,
                body=body,
                status="received",
                provider=provider,
                external_id=external_id,
                in_reply_to=in_reply_to,
                received_at=received_at,
            )
        )


async def _sync_platform_email_inbox() -> None:
    if not platform_inbox_configured():
        return
    async with SessionLocal() as session:
        state = await session.get(RuntimeHeartbeat, "platform_email_inbox")
        try:
            details = json.loads(state.details_json or "{}") if state else {}
            last_uid = int(details.get("last_uid") or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            last_uid = 0
    mails = await fetch_imap(platform_imap_config(), last_uid)
    max_uid = last_uid
    for mail in mails:
        max_uid = max(max_uid, mail.uid)
        parent_id = message_id_from_reply_address(mail.recipient)
        if parent_id is None:
            continue
        async with SessionLocal.begin() as session:
            parent = await session.get(CommunicationMessage, parent_id, with_for_update=True)
            if (
                parent is None
                or parent.direction != "outgoing"
                or parent.channel != "email"
                or parent.provider != "zahlmeister_email"
            ):
                continue
            if mail.message_id:
                duplicate = await session.scalar(
                    select(CommunicationMessage.id).where(
                        CommunicationMessage.direction == "incoming",
                        CommunicationMessage.external_id == mail.message_id,
                    )
                )
                if duplicate is not None:
                    continue
            session.add(
                CommunicationMessage(
                    organization_id=parent.organization_id,
                    collection_id=parent.collection_id,
                    collection_participant_id=parent.collection_participant_id,
                    kind="reply",
                    channel="email",
                    delivery_mode="internal",
                    direction="incoming",
                    sender=mail.sender,
                    recipient=mail.recipient,
                    subject=mail.subject,
                    body=mail.text,
                    status="received",
                    provider="zahlmeister_email",
                    external_id=mail.message_id,
                    in_reply_to=mail.in_reply_to,
                    received_at=datetime.now(UTC),
                )
            )
    async with SessionLocal.begin() as session:
        state = await session.get(RuntimeHeartbeat, "platform_email_inbox", with_for_update=True)
        if state is None:
            session.add(
                RuntimeHeartbeat(
                    name="platform_email_inbox",
                    last_seen_at=datetime.now(UTC),
                    details_json=json.dumps({"last_uid": max_uid}),
                )
            )
        else:
            state.last_seen_at = datetime.now(UTC)
            state.details_json = json.dumps({"last_uid": max_uid})


async def _sync_smtp_inbox(channel_setting: CommunicationChannelSetting) -> None:
    config = decrypt_config(channel_setting.encrypted_config)
    if not config.get("imap_host"):
        return
    try:
        last_uid = int(channel_setting.sync_cursor or 0)
    except ValueError:
        last_uid = 0
    mails = await fetch_imap(config, last_uid)
    max_uid = last_uid
    for mail in mails:
        max_uid = max(max_uid, mail.uid)
        await _store_incoming_email(
            channel_setting,
            provider="smtp_imap",
            candidates=[mail.in_reply_to or "", *reversed(mail.references)],
            external_id=mail.message_id,
            in_reply_to=mail.in_reply_to,
            sender=mail.sender,
            recipient=mail.recipient,
            subject=mail.subject,
            body=mail.text,
            received_at=datetime.now(UTC),
        )
    async with SessionLocal.begin() as session:
        stored = await session.get(CommunicationChannelSetting, channel_setting.id, with_for_update=True)
        if stored:
            if max_uid > last_uid:
                stored.sync_cursor = str(max_uid)
            stored.status = "connected"
            stored.last_error = None


async def _sync_microsoft365_inbox(channel_setting: CommunicationChannelSetting) -> None:
    if channel_setting.connection_id is None:
        raise ValueError("Microsoft 365 connection missing")
    mails, cursor = await microsoft365.fetch_inbox(channel_setting.connection_id, channel_setting.sync_cursor)
    for mail in mails:
        await _store_incoming_email(
            channel_setting,
            provider="microsoft365",
            candidates=[mail.conversation_id or "", mail.in_reply_to or "", *reversed(mail.references)],
            external_id=mail.external_id,
            in_reply_to=mail.in_reply_to,
            sender=mail.sender,
            recipient=mail.recipient,
            subject=mail.subject,
            body=mail.text,
            received_at=mail.received_at,
        )
    async with SessionLocal.begin() as session:
        stored = await session.get(CommunicationChannelSetting, channel_setting.id, with_for_update=True)
        if stored:
            stored.sync_cursor = cursor
            stored.status = "connected"
            stored.last_error = None


# --- Periodic job handlers ---------------------------------------------------------------
# A failing sync is recorded on its integration and not retried with backoff: the
# scheduler queues the next round anyway.


async def sync_platform_inbox(_job: ScheduledJob) -> None:
    try:
        await _sync_platform_email_inbox()
    except Exception:
        logger.exception("Platform reply inbox sync failed", extra={"event": "platform_email_inbox_sync_failed"})


async def sync_inbox(job: ScheduledJob) -> None:
    setting_id = UUID(json.loads(job.payload)["channel_setting_id"])
    async with SessionLocal() as session:
        channel_setting = await session.get(CommunicationChannelSetting, setting_id)
        if channel_setting is None:
            return
        session.expunge(channel_setting)
    try:
        if channel_setting.provider == "smtp_imap":
            await _sync_smtp_inbox(channel_setting)
        elif channel_setting.provider == "microsoft365":
            await _sync_microsoft365_inbox(channel_setting)
    except Exception as exc:
        logger.exception(
            "Internal email inbox sync failed",
            extra={
                "event": "email_inbox_sync_failed",
                "provider": channel_setting.provider,
                "organization_id": str(channel_setting.organization_id),
            },
        )
        async with SessionLocal.begin() as session:
            stored = await session.get(CommunicationChannelSetting, channel_setting.id, with_for_update=True)
            if stored:
                stored.status = "error"
                stored.last_error = str(exc)[:2000]


async def sync_bank(job: ScheduledJob) -> None:
    connection_id = UUID(json.loads(job.payload)["connection_id"])
    try:
        result = await bank_sync.sync_connection(connection_id)
    except Exception as exc:
        logger.exception("BankSync failed for %s", connection_id)
        await bank_sync.mark_connection_error(connection_id, str(exc))
        return
    logger.info(
        "BankSync %s: imported=%s auto=%s review=%s duplicates=%s",
        connection_id,
        result["imported"],
        result["auto_matched"],
        result["needs_review"],
        result["duplicates"],
    )


async def sync_billing(job: ScheduledJob) -> None:
    organization_id = UUID(json.loads(job.payload)["organization_id"])
    try:
        async with SessionLocal.begin() as session:
            await sync_mollie_subscription(session, organization_id)
    except Exception:
        logger.exception(
            "Mollie billing sync failed",
            extra={"event": "mollie_billing_sync_failed", "organization_id": str(organization_id)},
        )


HANDLERS: dict[str, Callable[[ScheduledJob], Awaitable[None]]] = {
    JOB_SEND_COLLECTION: send_collection,
    JOB_SEND_REMINDERS: send_reminders,
    JOB_SEND_MESSAGE: send_message,
    JOB_SYNC_PLATFORM_INBOX: sync_platform_inbox,
    JOB_SYNC_INBOX: sync_inbox,
    JOB_SYNC_BANK_CONNECTION: sync_bank,
    JOB_SYNC_BILLING: sync_billing,
}


async def run_job(job: ScheduledJob) -> None:
    handler = HANDLERS.get(job.job_type)
    if handler is None:
        raise ValueError(f"Unknown job type: {job.job_type}")
    await handler(job)
    await complete_job(job)


# --- Periodic enqueueing (scheduler) --------------------------------------------------------


async def enqueue_inbox_syncs() -> int:
    queued = 0
    async with SessionLocal.begin() as session:
        if platform_inbox_configured():
            queued += await enqueue_unique(
                session,
                job_type=JOB_SYNC_PLATFORM_INBOX,
                dedupe_key="sync:platform_inbox",
                priority=PRIORITY_SYNC,
            )
        rows = (
            await session.execute(
                select(CommunicationChannelSetting.id, CommunicationChannelSetting.organization_id).where(
                    CommunicationChannelSetting.channel == "email",
                    CommunicationChannelSetting.mode == "internal",
                    CommunicationChannelSetting.provider.in_(["smtp_imap", "microsoft365"]),
                )
            )
        ).all()
        for setting_id, organization_id in rows:
            queued += await enqueue_unique(
                session,
                job_type=JOB_SYNC_INBOX,
                dedupe_key=f"sync:inbox:{setting_id}",
                organization_id=organization_id,
                payload={"channel_setting_id": str(setting_id)},
                priority=PRIORITY_SYNC,
            )
    return queued


async def enqueue_bank_syncs() -> int:
    cutoff = datetime.now(UTC) - BANK_SYNC_INTERVAL
    queued = 0
    async with SessionLocal.begin() as session:
        rows = (
            await session.execute(
                select(BankSyncConnection.id, BankSyncConnection.organization_id).where(
                    BankSyncConnection.provider == "ponto",
                    BankSyncConnection.status.in_(["connected", "error"]),
                    (BankSyncConnection.last_sync_at.is_(None) | (BankSyncConnection.last_sync_at <= cutoff)),
                )
            )
        ).all()
        for connection_id, organization_id in rows:
            queued += await enqueue_unique(
                session,
                job_type=JOB_SYNC_BANK_CONNECTION,
                dedupe_key=f"sync:bank:{connection_id}",
                organization_id=organization_id,
                payload={"connection_id": str(connection_id)},
                priority=PRIORITY_SYNC,
            )
    return queued


async def enqueue_billing_syncs() -> int:
    if not mollie_billing_configured():
        return 0
    now = datetime.now(UTC)
    queued = 0
    async with SessionLocal.begin() as session:
        subscription_orgs = set(
            (
                await session.execute(
                    select(StoreSubscription.organization_id).where(
                        StoreSubscription.provider == "mollie",
                        or_(
                            StoreSubscription.status == "pending",
                            StoreSubscription.status == "grace_period",
                            (
                                StoreSubscription.auto_renew.is_(True)
                                & StoreSubscription.expires_at.is_not(None)
                                & (StoreSubscription.expires_at <= now)
                            ),
                        ),
                    )
                )
            ).scalars().all()
        )
        invoice_orgs = set(
            (
                await session.execute(
                    select(BillingInvoice.organization_id).where(
                        BillingInvoice.provider == "mollie",
                        BillingInvoice.status.in_(OPEN_INVOICE_STATUSES),
                    )
                )
            ).scalars().all()
        )
        for organization_id in subscription_orgs | invoice_orgs:
            queued += await enqueue_unique(
                session,
                job_type=JOB_SYNC_BILLING,
                dedupe_key=f"sync:billing:{organization_id}",
                organization_id=organization_id,
                payload={"organization_id": str(organization_id)},
                priority=PRIORITY_SYNC,
            )
    return queued


class Scheduler:
    """Periodic work, active in exactly one worker process at a time.

    Leadership is a session-level advisory lock on a dedicated connection; it is
    released by PostgreSQL when that connection ends, so a crashed leader is
    replaced by a standby within SCHEDULER_STANDBY_SECONDS.
    """

    def __init__(self) -> None:
        self.connection: AsyncConnection | None = None
        self.leader = False
        self._due: dict[str, float] = {}

    async def _acquire(self) -> bool:
        connection = await engine.connect()
        try:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": SCHEDULER_LOCK_KEY}
                )
            )
            # Session-level advisory locks outlive the transaction; ending it keeps
            # the connection from sitting idle in a transaction.
            await connection.commit()
        except Exception:
            await connection.close()
            raise
        if acquired:
            self.connection = connection
        else:
            await connection.close()
        return acquired

    async def _confirm(self) -> None:
        assert self.connection is not None
        await self.connection.execute(text("SELECT 1"))
        await self.connection.commit()

    async def release(self) -> None:
        connection, self.connection = self.connection, None
        was_leader, self.leader = self.leader, False
        if connection is not None:
            try:
                if was_leader:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": SCHEDULER_LOCK_KEY}
                    )
                    await connection.commit()
            except Exception:
                pass
            try:
                await connection.close()
            except Exception:
                pass

    async def _every(self, name: str, interval: float, task: Callable[[], Awaitable[object]]) -> None:
        now = time.monotonic()
        if now < self._due.get(name, 0.0):
            return
        self._due[name] = now + interval
        try:
            await task()
        except Exception:
            logger.exception("Scheduled task failed", extra={"event": "scheduler_task_failed", "task": name})

    async def tick(self) -> None:
        await self._every("stale_recovery", STALE_RECOVERY_SECONDS, recover_stale_jobs)
        await self._every("inbox_sync", INBOX_SYNC_SECONDS, enqueue_inbox_syncs)
        await self._every("bank_sync", BANK_SYNC_CHECK_SECONDS, enqueue_bank_syncs)
        await self._every("billing_sync", BILLING_SYNC_SECONDS, enqueue_billing_syncs)
        await self._every("purge", PURGE_SECONDS, purge_finished_jobs)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                if not self.leader:
                    self.leader = await self._acquire()
                    if self.leader:
                        self._due.clear()
                        logger.info("Worker %s is now the scheduler", WORKER_ID, extra={"event": "scheduler_acquired"})
                if self.leader:
                    await self._confirm()
                    await self.tick()
            except Exception:
                logger.exception("Scheduler lost its database connection", extra={"event": "scheduler_lost"})
                await self.release()
            await _sleep(stop, SCHEDULER_TICK_SECONDS if self.leader else SCHEDULER_STANDBY_SECONDS)
        await self.release()


# --- Process -------------------------------------------------------------------------------


async def job_slot(slot: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            job = await claim_job()
        except Exception:
            logger.exception("Claiming a job failed", extra={"event": "job_claim_failed", "slot": slot})
            await _sleep(stop, 5)
            continue
        if job is None:
            await _sleep(stop, settings.worker_poll_seconds)
            continue
        try:
            await run_job(job)
        except Exception as exc:
            logger.exception(
                "Job failed",
                extra={
                    "event": "job_exception",
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "attempt": job.attempts,
                    "organization_id": str(job.organization_id) if job.organization_id else None,
                },
            )
            try:
                await fail_job(job, exc)
            except Exception:
                logger.exception("Recording a job failure failed", extra={"event": "job_fail_record_failed"})


async def heartbeat_loop(stop: asyncio.Event, scheduler: Scheduler) -> None:
    while not stop.is_set():
        try:
            await update_worker_heartbeat(scheduler_active=scheduler.leader)
        except Exception:
            logger.exception("Worker heartbeat failed", extra={"event": "worker_heartbeat_failed"})
        await _sleep(stop, settings.worker_heartbeat_seconds)


async def main() -> None:
    logger.info(
        "Zahlmeister worker started",
        extra={"event": "worker_started", "worker_id": WORKER_ID, "slots": settings.worker_concurrency},
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    await recover_stale_jobs()
    scheduler = Scheduler()
    await asyncio.gather(
        heartbeat_loop(stop, scheduler),
        scheduler.run(stop),
        *(job_slot(slot, stop) for slot in range(max(1, settings.worker_concurrency))),
    )
    SMTP_POOL.close_all()
    await engine.dispose()
    logger.info("Zahlmeister worker stopped", extra={"event": "worker_stopped", "worker_id": WORKER_ID})


if __name__ == "__main__":
    asyncio.run(main())
