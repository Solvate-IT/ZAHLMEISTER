import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import (
    CollectionParticipant,
    CommunicationConnection,
    CommunicationMessage,
    OnlinePaymentAttempt,
    OnlinePaymentConnection,
    Payment,
)
from app.services.channel_strategy import set_channel_knowledge
from app.services.communications import normalize_phone
from app.services.message_dispatch import queue_failed_channel_fallback
from app.services.mollie import mollie_provider

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_CHANNEL_MAP = {
    "SMS": "sms",
    "WHATSAPP": "whatsapp",
    "TELEGRAM": "telegram",
    "EMAIL": "email",
}

_PERMANENT_WHATSAPP_FAILURE_MARKERS = (
    "NOT_REGISTERED",
    "NOT_WHATSAPP_USER",
    "NOT A WHATSAPP USER",
    "NO_WHATSAPP_ACCOUNT",
    "RECIPIENT_NOT_FOUND",
    "DESTINATION_NOT_FOUND",
    "INVALID_DESTINATION",
)


def _first(data: Any, *paths: tuple[str, ...] | str) -> Any:
    for path in paths:
        keys = (path,) if isinstance(path, str) else path
        current = data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if current not in (None, "", []):
            return current
    return None


def _normalize_channel(item: dict[str, Any]) -> str | None:
    raw = str(
        _first(item, "channel", "integrationType", "platform", "productName") or ""
    ).upper().replace(" ", "_").replace("-", "_")
    if raw in _CHANNEL_MAP:
        return _CHANNEL_MAP[raw]
    if "WHATSAPP" in raw:
        return "whatsapp"
    if "TELEGRAM" in raw:
        return "telegram"
    if raw == "SMS":
        return "sms"
    if "EMAIL" in raw:
        return "email"
    return None


def _text(item: dict[str, Any]) -> str:
    value = _first(
        item,
        ("message", "text"),
        ("message", "body"),
        ("content", "body", "text"),
        ("content", "text"),
        "text",
        "body",
    )
    if isinstance(value, str):
        return value
    if value is None:
        message_type = _first(item, ("message", "type"), ("content", "body", "type"))
        return f"[{message_type}]" if message_type else ""
    return json.dumps(value, ensure_ascii=False)


def _event_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "events", "messages", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _external_id(item: dict[str, Any]) -> str | None:
    value = _first(item, "messageId", "messageID", "id", ("message", "id"))
    return str(value) if value else None


def _callback_id(item: dict[str, Any]) -> UUID | None:
    value = _first(item, "callbackData", ("metadata", "callbackData"))
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _reply_to_external_id(item: dict[str, Any]) -> str | None:
    value = _first(
        item,
        "inReplyTo",
        "replyToMessageId",
        ("context", "messageId"),
        ("context", "id"),
        ("message", "context", "messageId"),
        ("message", "context", "id"),
    )
    return str(value) if value else None


def _sender(item: dict[str, Any]) -> str:
    return str(
        _first(
            item,
            "from",
            "sender",
            ("source", "address"),
            ("source", "from"),
            ("contact", "phoneNumber"),
            ("contact", "userId"),
        )
        or ""
    ).strip()


def _recipient(item: dict[str, Any]) -> str:
    return str(
        _first(
            item,
            "to",
            "destination",
            ("destination", "address"),
            ("destination", "to"),
        )
        or ""
    ).strip()


def _status_value(item: dict[str, Any]) -> str | None:
    raw = _first(
        item,
        "eventType",
        "event",
        "status",
        ("status", "groupName"),
        ("status", "name"),
        "deliveryStatus",
    )
    if isinstance(raw, dict):
        raw = raw.get("name") or raw.get("groupName")
    if not raw:
        return None
    value = str(raw).strip().upper()
    if value in {"SEEN", "READ", "READ_BY_RECIPIENT"}:
        return "read"
    if "DELIVER" in value:
        return "delivered"
    if "FAIL" in value or "REJECT" in value or "EXPIRE" in value or "UNDELIVER" in value:
        return "failed"
    if "PENDING" in value or value in {"SENT", "ACCEPTED"}:
        return "sent"
    if value == "INBOUND_MESSAGE":
        return None
    return value.lower()


def _is_inbound(item: dict[str, Any]) -> bool:
    event = str(_first(item, "eventType", "event", "direction") or "").upper()
    if event in {"INBOUND_MESSAGE", "INBOUND", "MO"}:
        return True
    return bool(_sender(item) and _text(item) and not _status_value(item))


def _permanent_whatsapp_failure(item: dict[str, Any]) -> bool:
    normalized = json.dumps(item, ensure_ascii=True, sort_keys=True).upper()
    return any(marker in normalized for marker in _PERMANENT_WHATSAPP_FAILURE_MARKERS)


def _advanced_delivery_status(current: str, new_status: str) -> str:
    """Advance provider status without allowing late events to undo stronger evidence."""
    if new_status == "read":
        return "read"
    if new_status == "delivered":
        return "read" if current == "read" else "delivered"
    if new_status == "failed":
        return current if current in {"delivered", "read"} else "failed"
    if new_status == "sent":
        return "sent" if current in {"queued", "sent"} else current
    return current


async def _connection(webhook_key: str) -> CommunicationConnection:
    async with SessionLocal() as session:
        connection = await session.scalar(
            select(CommunicationConnection).where(
                CommunicationConnection.webhook_key == webhook_key,
                CommunicationConnection.provider == "infobip",
                CommunicationConnection.status == "connected",
            )
        )
        if connection is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
        session.expunge(connection)
        return connection


async def _find_outgoing(
    organization_id,
    *,
    channel: str | None,
    sender: str,
    callback_id: UUID | None,
    reply_to_external_id: str | None,
) -> CommunicationMessage | None:
    async with SessionLocal() as session:
        if callback_id:
            message = await session.get(CommunicationMessage, callback_id)
            if (
                message is not None
                and message.organization_id == organization_id
                and message.direction == "outgoing"
            ):
                session.expunge(message)
                return message
        if reply_to_external_id:
            message = await session.scalar(
                select(CommunicationMessage).where(
                    CommunicationMessage.organization_id == organization_id,
                    CommunicationMessage.direction == "outgoing",
                    CommunicationMessage.external_id == reply_to_external_id,
                )
            )
            if message is not None:
                session.expunge(message)
                return message
        if not channel or not sender:
            return None
        candidates = {sender}
        if channel in {"sms", "whatsapp"}:
            normalized = normalize_phone(sender)
            if normalized:
                candidates.add(normalized)
        message = await session.scalar(
            select(CommunicationMessage)
            .where(
                CommunicationMessage.organization_id == organization_id,
                CommunicationMessage.channel == channel,
                CommunicationMessage.direction == "outgoing",
                CommunicationMessage.recipient.in_(candidates),
            )
            .order_by(CommunicationMessage.created_at.desc())
            .limit(1)
        )
        if message is not None:
            session.expunge(message)
        return message


async def _store_incoming(
    outgoing: CommunicationMessage,
    *,
    sender: str,
    recipient: str | None,
    body: str,
    external_id: str | None,
    in_reply_to: str | None,
    raw: dict[str, Any],
) -> None:
    async with SessionLocal.begin() as session:
        locked_outgoing = await session.get(
            CommunicationMessage, outgoing.id, with_for_update=True
        )
        if locked_outgoing is None or locked_outgoing.organization_id != outgoing.organization_id:
            return
        if external_id:
            duplicate = await session.scalar(
                select(CommunicationMessage.id).where(
                    CommunicationMessage.organization_id == outgoing.organization_id,
                    CommunicationMessage.external_id == external_id,
                    CommunicationMessage.direction == "incoming",
                )
            )
            if duplicate is not None:
                return
        normalized_sender = (
            normalize_phone(sender) if outgoing.channel in {"sms", "whatsapp"} else sender
        )
        session.add(
            CommunicationMessage(
                organization_id=outgoing.organization_id,
                collection_id=outgoing.collection_id,
                collection_participant_id=outgoing.collection_participant_id,
                kind="reply",
                channel=outgoing.channel,
                delivery_mode="internal",
                direction="incoming",
                sender=normalized_sender or sender,
                recipient=recipient,
                body=body,
                status="received",
                provider="infobip",
                external_id=external_id,
                in_reply_to=in_reply_to or outgoing.external_id,
                received_at=datetime.now(UTC),
                metadata_json=json.dumps(raw, ensure_ascii=False)[:20000],
            )
        )
        if outgoing.channel == "whatsapp":
            cp = await session.get(CollectionParticipant, locked_outgoing.collection_participant_id)
            if cp is not None:
                await set_channel_knowledge(
                    session,
                    cp.participant_id,
                    "whatsapp",
                    availability="available",
                )


async def _update_delivery(
    organization_id,
    *,
    callback_id: UUID | None,
    external_id: str | None,
    new_status: str,
    raw: dict[str, Any],
) -> None:
    async with SessionLocal.begin() as session:
        message = None
        if callback_id:
            message = await session.get(CommunicationMessage, callback_id, with_for_update=True)
            if message is not None and message.organization_id != organization_id:
                message = None
        if message is None and external_id:
            message = await session.scalar(
                select(CommunicationMessage)
                .where(
                    CommunicationMessage.organization_id == organization_id,
                    CommunicationMessage.direction == "outgoing",
                    CommunicationMessage.external_id == external_id,
                )
                .with_for_update()
            )
        if message is None:
            return

        previous_status = message.status
        message.status = _advanced_delivery_status(previous_status, new_status)
        message.metadata_json = json.dumps(raw, ensure_ascii=False)[:20000]

        if message.channel != "whatsapp":
            return
        cp = await session.get(CollectionParticipant, message.collection_participant_id)
        if cp is None:
            return
        if new_status in {"delivered", "read"}:
            await set_channel_knowledge(
                session,
                cp.participant_id,
                "whatsapp",
                availability="available",
            )
        elif (
            new_status == "failed"
            and previous_status not in {"delivered", "read"}
            and _permanent_whatsapp_failure(raw)
        ):
            await set_channel_knowledge(
                session,
                cp.participant_id,
                "whatsapp",
                availability="unavailable",
                failure_reason="Provider reports that the WhatsApp destination is unavailable",
            )
            await queue_failed_channel_fallback(session, failed_message=message)


@router.post("/infobip/{webhook_key}", status_code=204)
async def infobip_webhook(webhook_key: str, request: Request) -> Response:
    connection = await _connection(webhook_key)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from exc

    for item in _event_items(payload):
        channel = _normalize_channel(item)
        callback_id = _callback_id(item)
        external_id = _external_id(item)
        reply_to = _reply_to_external_id(item)
        sender = _sender(item)
        recipient = _recipient(item)

        if _is_inbound(item):
            outgoing = await _find_outgoing(
                connection.organization_id,
                channel=channel,
                sender=sender,
                callback_id=callback_id,
                reply_to_external_id=reply_to,
            )
            if outgoing is not None:
                await _store_incoming(
                    outgoing,
                    sender=sender,
                    recipient=recipient or None,
                    body=_text(item),
                    external_id=external_id,
                    in_reply_to=reply_to,
                    raw=item,
                )
            continue

        delivery_status = _status_value(item)
        if delivery_status:
            await _update_delivery(
                connection.organization_id,
                callback_id=callback_id,
                external_id=external_id,
                new_status=delivery_status,
                raw=item,
            )

    return Response(status_code=204)


@router.post("/mollie/{webhook_key}", status_code=200)
async def mollie_webhook(webhook_key: str, request: Request) -> Response:
    try:
        form = await request.form()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook") from exc
    posted_id = str(form.get("id") or "").strip()

    async with SessionLocal.begin() as session:
        attempt = await session.scalar(
            select(OnlinePaymentAttempt)
            .where(OnlinePaymentAttempt.webhook_key == webhook_key)
            .with_for_update()
        )
        if attempt is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
        connection = await session.get(OnlinePaymentConnection, attempt.connection_id, with_for_update=True)
        if connection is None or connection.provider != "mollie":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment connection not found")
        external_id = posted_id or attempt.external_id or ""
        if not external_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment id missing")
        if attempt.external_id and external_id != attempt.external_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment id mismatch")

        try:
            provider_payment = await mollie_provider.get_payment(session, connection, external_id)
        except Exception as exc:
            connection.last_error = str(exc)[:2000]
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Payment status unavailable") from exc

        if provider_payment.external_id != external_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment id mismatch")
        if (
            provider_payment.amount != attempt.amount
            or provider_payment.currency.upper() != attempt.currency.upper()
        ):
            attempt.status = "failed"
            attempt.last_error = "Provider payment amount or currency does not match"
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=attempt.last_error)

        attempt.external_id = provider_payment.external_id
        attempt.status = provider_payment.status
        attempt.payment_method = provider_payment.method
        attempt.paid_at = provider_payment.paid_at
        attempt.expires_at = provider_payment.expires_at
        attempt.last_error = None
        connection.last_error = None

        if provider_payment.status == "paid":
            cp = await session.get(CollectionParticipant, attempt.collection_participant_id, with_for_update=True)
            if cp is None:
                raise HTTPException(status_code=404, detail="Collection participant not found")
            existing = await session.scalar(
                select(Payment.id).where(
                    Payment.provider == "mollie",
                    Payment.external_reference == provider_payment.external_id,
                )
            )
            booked_at = provider_payment.paid_at or datetime.now(UTC)
            if existing is None:
                session.add(
                    Payment(
                        collection_participant_id=cp.id,
                        amount=provider_payment.amount,
                        currency=provider_payment.currency,
                        method="online",
                        provider="mollie",
                        external_reference=provider_payment.external_id,
                        booked_at=booked_at,
                        details=json.dumps(
                            {
                                "provider_method": provider_payment.method,
                                "online_payment_attempt_id": str(attempt.id),
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
            if cp.status != "paid":
                cp.status = "paid"
                cp.paid_at = booked_at

    return Response(status_code=200)
