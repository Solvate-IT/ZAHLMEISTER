from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import StoreSubscription
from app.services.mollie_billing_core import (
    MOLLIE_PROVIDER,
    MollieBillingConflict,
    MollieBillingUnavailable,
    billing_configured,
    cancel_subscription,
)
from app.services.secrets import decrypt_config, encrypt_config


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _can_reactivate(subscription: StoreSubscription, data: dict[str, object], now: datetime) -> bool:
    if subscription.status not in {"active", "cancelled"}:
        return False
    if subscription.expires_at is None or _utc(subscription.expires_at) <= now:
        return False
    customer_id = data.get("mollie_customer_id")
    mandate_id = data.get("mandate_id")
    return (
        isinstance(customer_id, str)
        and bool(customer_id.strip())
        and isinstance(mandate_id, str)
        and bool(mandate_id.strip())
    )


async def set_auto_renew(
    session: AsyncSession,
    organization_id: UUID,
    enabled: bool,
) -> None:
    if not enabled:
        await cancel_subscription(session, organization_id)
        return

    if not billing_configured():
        raise MollieBillingUnavailable("Mollie billing is not configured")

    subscription = await session.scalar(
        select(StoreSubscription)
        .where(
            StoreSubscription.organization_id == organization_id,
            StoreSubscription.provider == MOLLIE_PROVIDER,
        )
        .with_for_update()
    )
    if subscription is None:
        raise MollieBillingConflict("No Mollie subscription exists")

    data = decrypt_config(subscription.verification_data_encrypted)
    now = datetime.now(UTC)
    if not _can_reactivate(subscription, data, now):
        raise MollieBillingConflict("Mollie automatic renewal cannot be enabled")

    subscription.auto_renew = True
    subscription.cancelled_at = None
    subscription.status = "active"
    subscription.last_verified_at = now
    data.pop("grace_until", None)
    subscription.verification_data_encrypted = encrypt_config(data)
    await session.flush()
