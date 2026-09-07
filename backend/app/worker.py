import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.observability import configure_logging
from app.db.session import SessionLocal
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
from app.services import microsoft365
from app.services.bank_sync import sync_connection as sync_bank_connection
from app.services.central_mail import (
    message_id_from_reply_address,
    platform_imap_config,
    platform_inbox_configured,
    reply_address,
)
from app.services.channel_strategy import load_channel_runtimes, set_channel_knowledge
from app.services.communications import fetch_imap, send_smtp_email
from app.services.infobip import (
    authorization_for_connection,
    connection_is_active,
    connection_webhook_url,
    send_infobip_message,
)
from app.services.message_dispatch import queue_collection_messages
from app.services.message_renderer import canonical_from_stored_message
from app.services.reminders import deserialize_reminder_rules, reminder_schedule
from app.services.retry import is_retryable_exception, retry_delay_seconds
from app.services.secrets import decrypt_config

configure_logging()
logger = logging.getLogger("zahlmeister.worker")
INBOX_SYNC_SECONDS = 60
BANK_SYNC_CHECK_SECONDS = 300
BANK_SYNC_INTERVAL = timedelta(hours=1)


async def claim_job() -> ScheduledJob | None:
    async with SessionLocal.begin() as session:
        stmt = (
            select(ScheduledJob)
            .where(ScheduledJob.status == "pending", ScheduledJob.scheduled_at <= datetime.now(UTC))
            .order_by(ScheduledJob.scheduled_at)
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


async def fail_job(job: ScheduledJob, error: Exception) -> None:
    retryable = is_retryable_exception(error) and job.attempts < settings.job_max_attempts
    delay = retry_delay_seconds(
        job.attempts,
        base_seconds=settings.job_retry_base_seconds,
        max_seconds=settings.job_retry_max_seconds,
        jitter_fraction=settings.job_retry_jitter,
    )
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
            if stored.job_type == "send_message":
                try:
                    message_id = UUID(json.loads(stored.payload)["message_id"])
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    message_id = None
                if message_id is not None:
                    message = await session.get(CommunicationMessage, message_id, with_for_update=True)
                    if message is not None and message.status not in {"sent", "delivered", "read"}:
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


async def update_worker_heartbeat() -> None:
    now = datetime.now(UTC)
    async with SessionLocal.begin() as session:
        heartbeat = await session.get(RuntimeHeartbeat, "worker", with_for_update=True)
        if heartbeat is None:
            session.add(RuntimeHeartbeat(name="worker", last_seen_at=now, details_json="{}"))
        else:
            heartbeat.last_seen_at = now


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


async def _queue_message_jobs(collection_id: UUID, *, kind: str) -> int:
    async with SessionLocal.begin() as session:
        collection = await session.get(Collection, collection_id, with_for_update=True)
        if collection is None:
            raise ValueError(f"Collection {collection_id} not found")
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


async def send_collection(job: ScheduledJob) -> None:
    collection_id = UUID(json.loads(job.payload)["collection_id"])
    first_activation = False
    send_at = datetime.now(UTC)
    due_at = None
    organization_id = None
    reminder_rules: list[dict] = []
    async with SessionLocal.begin() as session:
        collection = await session.get(Collection, collection_id, with_for_update=True)
        if collection is None:
            raise ValueError(f"Collection {collection_id} not found")
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
                    payload = json.dumps(
                        {"collection_id": str(collection_id), "automatic": True, "rule": rule_key}
                    )
                    existing = await session.scalar(
                        select(ScheduledJob.id)
                        .where(
                            ScheduledJob.job_type == "send_reminders",
                            ScheduledJob.payload == payload,
                            ScheduledJob.status.in_(["pending", "running", "done"]),
                        )
                        .limit(1)
                    )
                    if existing is None:
                        session.add(
                            ScheduledJob(
                                organization_id=organization_id,
                                job_type="send_reminders",
                                payload=payload,
                                scheduled_at=scheduled_at,
                            )
                        )


async def send_reminders(job: ScheduledJob) -> None:
    collection_id = UUID(json.loads(job.payload)["collection_id"])
    queued = await _queue_message_jobs(collection_id, kind="reminder")
    logger.info("Collection %s reminder run; %s messages queued", collection_id, queued)


async def send_message(job: ScheduledJob) -> None:
    message_id = UUID(json.loads(job.payload)["message_id"])
    provider = ""
    sender = ""
    config: dict = {}
    connection_id: UUID | None = None
    recipient = ""
    channel = ""
    participant_id: UUID | None = None
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
        if message.kind == "reminder" and cp.status != "open":
            message.status = "skipped"
            message.error = "Payment already received"
            return
        if not message.recipient:
            message.status = "skipped"
            message.error = "No recipient"
            return

        content = canonical_from_stored_message(message)
        runtimes = await load_channel_runtimes(session, message.organization_id)
        runtime = runtimes.get(message.channel)
        if runtime is None or runtime.mode != "internal" or not runtime.configured:
            raise ValueError(f"Internal {message.channel} is not configured")
        provider = message.provider or runtime.provider or ""
        sender = runtime.sender or ""
        config = runtime.config
        connection_id = runtime.connection_id
        recipient = message.recipient
        channel = message.channel
        participant_id = cp.participant_id
        organization = await session.get(Organization, message.organization_id)
        if organization is not None:
            organization_name = organization.name

    message_header_id = f"<zm-{message_id}@zahlmeister>"
    if provider == "zahlmeister_email":
        external_id = await send_smtp_email(
            recipient=recipient,
            content=content,
            config={
                **config,
                "from_name": organization_name,
                "reply_to": reply_address(message_id),
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
        if channel == "whatsapp" and participant_id is not None:
            await set_channel_knowledge(session, participant_id, "whatsapp", availability="available")


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


async def sync_internal_email_inboxes() -> None:
    try:
        await _sync_platform_email_inbox()
    except Exception:
        logger.exception("Platform reply inbox sync failed", extra={"event": "platform_email_inbox_sync_failed"})

    async with SessionLocal() as session:
        settings_rows = (
            await session.execute(
                select(CommunicationChannelSetting).where(
                    CommunicationChannelSetting.channel == "email",
                    CommunicationChannelSetting.mode == "internal",
                    CommunicationChannelSetting.provider.in_(["smtp_imap", "microsoft365"]),
                )
            )
        ).scalars().all()
        detached = []
        for item in settings_rows:
            session.expunge(item)
            detached.append(item)

    for channel_setting in detached:
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


async def sync_bank_connections() -> None:
    cutoff = datetime.now(UTC) - BANK_SYNC_INTERVAL
    async with SessionLocal() as session:
        ids = (
            await session.execute(
                select(BankSyncConnection.id).where(
                    BankSyncConnection.provider == "ponto",
                    BankSyncConnection.status.in_(["connected", "error"]),
                    (BankSyncConnection.last_sync_at.is_(None) | (BankSyncConnection.last_sync_at <= cutoff)),
                )
            )
        ).scalars().all()
    for connection_id in ids:
        try:
            async with SessionLocal.begin() as session:
                connection = await session.get(BankSyncConnection, connection_id, with_for_update=True)
                if connection is None:
                    continue
                result = await sync_bank_connection(session, connection)
                logger.info(
                    "BankSync %s: imported=%s auto=%s review=%s duplicates=%s",
                    connection_id,
                    result["imported"],
                    result["auto_matched"],
                    result["needs_review"],
                    result["duplicates"],
                )
        except Exception as exc:
            logger.exception("BankSync failed for %s", connection_id)
            async with SessionLocal.begin() as session:
                connection = await session.get(BankSyncConnection, connection_id, with_for_update=True)
                if connection:
                    connection.status = "error"
                    connection.last_error = str(exc)[:2000]


async def run_job(job: ScheduledJob) -> None:
    handlers = {"send_collection": send_collection, "send_reminders": send_reminders, "send_message": send_message}
    handler = handlers.get(job.job_type)
    if handler is None:
        raise ValueError(f"Unknown job type: {job.job_type}")
    await handler(job)
    await complete_job(job)


async def main() -> None:
    logger.info("Zahlmeister worker started", extra={"event": "worker_started"})
    await recover_stale_jobs()
    await update_worker_heartbeat()
    next_inbox_sync = 0.0
    next_bank_sync = 0.0
    next_heartbeat = 0.0
    next_stale_recovery = 0.0
    while True:
        now_mono = time.monotonic()
        if now_mono >= next_heartbeat:
            await update_worker_heartbeat()
            next_heartbeat = now_mono + settings.worker_heartbeat_seconds
        if now_mono >= next_stale_recovery:
            await recover_stale_jobs()
            next_stale_recovery = now_mono + min(60, settings.job_stale_after_seconds / 3)
        if now_mono >= next_inbox_sync:
            await sync_internal_email_inboxes()
            next_inbox_sync = now_mono + INBOX_SYNC_SECONDS
        if now_mono >= next_bank_sync:
            await sync_bank_connections()
            next_bank_sync = now_mono + BANK_SYNC_CHECK_SECONDS
        job = await claim_job()
        if job is None:
            await asyncio.sleep(2)
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
            await fail_job(job, exc)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
