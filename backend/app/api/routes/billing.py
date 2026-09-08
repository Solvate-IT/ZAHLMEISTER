from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.models.entities import User
from app.schemas.billing import BillingEntitlementRead, BillingPurchaseContextRead
from app.services.billing import entitlement_for_organization, purchase_context

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/entitlement", response_model=BillingEntitlementRead)
async def entitlement(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BillingEntitlementRead:
    item = await entitlement_for_organization(session, user.organization_id)
    return BillingEntitlementRead(
        plan=item.plan,
        active=item.active,
        provider=item.provider,
        status=item.status,
        product_id=item.product_id,
        expires_at=item.expires_at,
        auto_renew=item.auto_renew,
    )


@router.get("/purchase-context", response_model=BillingPurchaseContextRead)
async def get_purchase_context(
    provider: Literal["apple", "google", "mollie"] = Query(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BillingPurchaseContextRead:
    try:
        context = await purchase_context(session, user.organization_id, provider)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported billing provider",
        ) from exc
    return BillingPurchaseContextRead.model_validate(context)
