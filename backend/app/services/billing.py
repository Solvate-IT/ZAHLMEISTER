from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import StoreSubscription
from app.services.secrets import encrypt_config

PRO_PRODUCT_ID = "zahlmeister.pro.yearly"
ENTITLED_STATUSES = {"active", "grace_period", "cancelled"}
PURCHASE_PROVIDERS = {"apple", "google", "mollie"}
STORE_STATUSES = {
    "pending",
    "active",
    "grace_period",
    "cancelled",
    "expired",
    "revoked",
    "on_hold",
}


@dataclass(frozen=True)
class Entitlement:
    active: bool
    plan: str
    provider: str | None
    status: str | None
    product_id: str | None
    expires_at: datetime | None
    auto_renew: bool | None


@dataclass(frozen=True)
class VerifiedSubscription:
    provider: str
    product_id: str
    external_reference: str
    account_token: str
    status: str
    purchased_at: datetime | None = None
    expires_at: datetime | None = None
    auto_renew: bool | None = None
    environment: str | None = None
    verification_data: dict[str, Any] | None = None


def subscription_is_entitled(
    subscription: StoreSubscription,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(UTC)
    if subscription.status not in ENTITLED_STATUSES:
        return False
    if subscription.status == "cancelled":
        return subscription.expires_at is not None and subscription.expires_at > current
    return subscription.expires_at is None or subscription.expires_at > current


def validate_verified_subscription(
    organization_id: UUID,
    verified: VerifiedSubscription,
) -> None:
    if verified.provider not in PURCHASE_PROVIDERS:
        raise ValueError("Unsupported billing provider")
    if verified.product_id != PRO_PRODUCT_ID:
        raise ValueError("Unexpected billing product")
    if verified.account_token != str(organization_id):
        raise ValueError("Purchase belongs to another Zahlmeister account")
    if verified.status not in STORE_STATUSES:
        raise ValueError("Unsupported subscription status")
    if not verified.external_reference.strip():
        raise ValueError("Subscription reference is missing")


async def apply_verified_subscription(
    session: AsyncSession,
    organization_id: UUID,
    verified: VerifiedSubscription,
) -> StoreSubscription:
    validate_verified_subscription(organization_id, verified)

    by_reference = await session.scalar(
        select(StoreSubscription)
        .where(StoreSubscription.external_reference == verified.external_reference)
        .with_for_update()
    )
    if by_reference is not None and (
        by_reference.organization_id != organization_id
        or by_reference.provider != verified.provider
    ):
        raise ValueError("Subscription reference is already assigned to another account")

    subscription = await session.scalar(
        select(StoreSubscription)
        .where(
            StoreSubscription.organization_id == organization_id,
            StoreSubscription.provider == verified.provider,
        )
        .with_for_update()
    )
    if subscription is None:
        subscription = StoreSubscription(
            organization_id=organization_id,
            provider=verified.provider,
            product_id=verified.product_id,
        )
        session.add(subscription)

    subscription.product_id = verified.product_id
    subscription.status = verified.status
    subscription.external_reference = verified.external_reference
    subscription.purchased_at = verified.purchased_at
    subscription.expires_at = verified.expires_at
    subscription.auto_renew = verified.auto_renew
    subscription.environment = verified.environment
    subscription.last_verified_at = datetime.now(UTC)
    subscription.cancelled_at = (
        datetime.now(UTC)
        if verified.status in {"cancelled", "expired", "revoked"}
        else None
    )
    if verified.verification_data is not None:
        subscription.verification_data_encrypted = encrypt_config(verified.verification_data)
    await session.flush()
    return subscription


async def active_entitlement_subscription(
    session: AsyncSession,
    organization_id: UUID,
) -> StoreSubscription | None:
    rows = (
        await session.execute(
            select(StoreSubscription)
            .where(
                StoreSubscription.organization_id == organization_id,
                StoreSubscription.status.in_(ENTITLED_STATUSES),
            )
            .order_by(StoreSubscription.expires_at.desc().nullsfirst())
        )
    ).scalars().all()
    now = datetime.now(UTC)
    return next((item for item in rows if subscription_is_entitled(item, now=now)), None)


async def latest_subscription(
    session: AsyncSession,
    organization_id: UUID,
) -> StoreSubscription | None:
    return await session.scalar(
        select(StoreSubscription)
        .where(StoreSubscription.organization_id == organization_id)
        .order_by(StoreSubscription.updated_at.desc(), StoreSubscription.created_at.desc())
        .limit(1)
    )


async def entitlement_for_organization(
    session: AsyncSession,
    organization_id: UUID,
) -> Entitlement:
    subscription = await active_entitlement_subscription(session, organization_id)
    if subscription is not None:
        return Entitlement(
            active=True,
            plan="pro",
            provider=subscription.provider,
            status=subscription.status,
            product_id=subscription.product_id,
            expires_at=subscription.expires_at,
            auto_renew=subscription.auto_renew,
        )

    latest = await latest_subscription(session, organization_id)
    return Entitlement(
        active=False,
        plan="free",
        provider=latest.provider if latest else None,
        status=latest.status if latest else None,
        product_id=latest.product_id if latest else None,
        expires_at=latest.expires_at if latest else None,
        auto_renew=latest.auto_renew if latest else None,
    )


async def purchase_context(
    session: AsyncSession,
    organization_id: UUID,
    provider: str,
) -> dict[str, object]:
    if provider not in PURCHASE_PROVIDERS:
        raise ValueError("Unsupported billing provider")

    entitlement = await entitlement_for_organization(session, organization_id)
    purchase_allowed = not entitlement.active
    reason = None
    if entitlement.active:
        reason = (
            "already_entitled_same_provider"
            if entitlement.provider == provider
            else "already_entitled_other_provider"
        )

    return {
        "provider": provider,
        "product_id": PRO_PRODUCT_ID,
        "account_token": str(organization_id),
        "purchase_allowed": purchase_allowed,
        "existing_provider": entitlement.provider,
        "existing_status": entitlement.status,
        "reason": reason,
    }
