from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Participant
from app.models.platform import StoreSubscription

FREE_PARTICIPANTS_PER_LIST = 10
PRO_PRODUCT_ID = "zahlmeister.pro.yearly"


async def active_subscription(
    session: AsyncSession, organization_id
) -> StoreSubscription | None:
    now = datetime.now(UTC)
    return await session.scalar(
        select(StoreSubscription)
        .where(
            StoreSubscription.organization_id == organization_id,
            StoreSubscription.status == "active",
            (StoreSubscription.expires_at.is_(None) | (StoreSubscription.expires_at > now)),
        )
        .order_by(StoreSubscription.expires_at.desc().nullsfirst())
    )


async def is_pro(session: AsyncSession, organization_id) -> bool:
    return await active_subscription(session, organization_id) is not None


async def plan_name(session: AsyncSession, organization_id) -> str:
    return "pro" if await is_pro(session, organization_id) else "free"


async def participant_capacity_available(
    session: AsyncSession,
    organization_id,
    list_id,
    *,
    adding: int = 1,
) -> bool:
    if adding <= 0 or await is_pro(session, organization_id):
        return True
    current = int(
        await session.scalar(select(func.count()).where(Participant.list_id == list_id)) or 0
    )
    return current + adding <= FREE_PARTICIPANTS_PER_LIST
