from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import StoreSubscription

PRO_PRODUCT_ID = "zahlmeister.pro.yearly"
ENTITLED_STATUSES = {"active", "grace_period"}
PURCHASE_PROVIDERS = {"apple", "google", "mollie"}


@dataclass(frozen=True)
class Entitlement:
    active: bool
    plan: str
    provider: str | None
    status: str | None
    product_id: str | None
    expires_at: datetime | None
    auto_renew: bool | None


def subscription_is_entitled(
    subscription: StoreSubscription,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(UTC)
    if subscription.status not in ENTITLED_STATUSES:
        return False
    return subscription.expires_at is None or subscription.expires_at > current


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


async def entitlement_for_organization(
    session: AsyncSession,
    organization_id: UUID,
) -> Entitlement:
    subscription = await active_entitlement_subscription(session, organization_id)
    if subscription is None:
        return Entitlement(
            active=False,
            plan="free",
            provider=None,
            status=None,
            product_id=None,
            expires_at=None,
            auto_renew=None,
        )
    return Entitlement(
        active=True,
        plan="pro",
        provider=subscription.provider,
        status=subscription.status,
        product_id=subscription.product_id,
        expires_at=subscription.expires_at,
        auto_renew=subscription.auto_renew,
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
