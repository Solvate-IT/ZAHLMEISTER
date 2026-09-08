from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Participant
from app.models.platform import StoreSubscription
from app.services.billing import PRO_PRODUCT_ID, active_entitlement_subscription

FREE_PARTICIPANTS_PER_LIST = 10


async def active_subscription(
    session: AsyncSession, organization_id
) -> StoreSubscription | None:
    return await active_entitlement_subscription(session, organization_id)


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
