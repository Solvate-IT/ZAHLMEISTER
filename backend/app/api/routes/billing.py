from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.db.session import SessionLocal
from app.models.entities import Organization, User
from app.schemas.billing import (
    BillingEntitlementRead,
    BillingPurchaseContextRead,
    MollieBillingCheckoutRead,
    MollieBillingConfigRead,
)
from app.services.billing import Entitlement, entitlement_for_organization, purchase_context
from app.services.mollie_billing import (
    MollieBillingConflict,
    MollieBillingUnavailable,
    MollieBillingVerificationError,
    billing_config,
    cancel_subscription,
    process_payment,
    start_checkout,
    sync_subscription,
)

router = APIRouter(prefix="/billing", tags=["billing"])


def _entitlement_read(item: Entitlement) -> BillingEntitlementRead:
    return BillingEntitlementRead(
        plan=item.plan,
        active=item.active,
        provider=item.provider,
        status=item.status,
        product_id=item.product_id,
        expires_at=item.expires_at,
        auto_renew=item.auto_renew,
    )


@router.get("/entitlement", response_model=BillingEntitlementRead)
async def entitlement(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BillingEntitlementRead:
    return _entitlement_read(await entitlement_for_organization(session, user.organization_id))


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


@router.get("/mollie/config", response_model=MollieBillingConfigRead)
async def mollie_config(_: User = Depends(get_current_user)) -> MollieBillingConfigRead:
    return MollieBillingConfigRead.model_validate(billing_config())


@router.post("/mollie/checkout", response_model=MollieBillingCheckoutRead)
async def mollie_checkout(user: User = Depends(get_current_user)) -> MollieBillingCheckoutRead:
    try:
        async with SessionLocal.begin() as session:
            organization = await session.get(Organization, user.organization_id)
            if organization is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Workspace not found",
                )
            item = await start_checkout(
                session,
                user.organization_id,
                customer_name=organization.name,
                customer_email=user.email,
            )
    except MollieBillingConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MollieBillingUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mollie subscription billing is unavailable",
        ) from exc
    return MollieBillingCheckoutRead(
        checkout_url=item.checkout_url,
        payment_id=item.payment_id,
        resumed=item.resumed,
    )


@router.post("/mollie/sync", response_model=BillingEntitlementRead)
async def mollie_sync(user: User = Depends(get_current_user)) -> BillingEntitlementRead:
    try:
        async with SessionLocal.begin() as session:
            await sync_subscription(session, user.organization_id)
            item = await entitlement_for_organization(session, user.organization_id)
    except MollieBillingVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Mollie subscription could not be verified",
        ) from exc
    except MollieBillingUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mollie subscription billing is unavailable",
        ) from exc
    return _entitlement_read(item)


@router.post("/mollie/cancel", response_model=BillingEntitlementRead)
async def mollie_cancel(user: User = Depends(get_current_user)) -> BillingEntitlementRead:
    try:
        async with SessionLocal.begin() as session:
            await cancel_subscription(session, user.organization_id)
            item = await entitlement_for_organization(session, user.organization_id)
    except MollieBillingConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MollieBillingUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mollie subscription billing is unavailable",
        ) from exc
    return _entitlement_read(item)


@router.post(
    "/mollie/webhook",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
async def mollie_webhook(payment_id: str = Form(alias="id")) -> None:
    try:
        async with SessionLocal.begin() as session:
            await process_payment(session, payment_id)
    except MollieBillingVerificationError:
        # A forged or stale payment reference must never grant an entitlement.
        return
    except MollieBillingUnavailable as exc:
        # A transient Mollie outage should cause Mollie to retry the webhook later.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing verification temporarily unavailable",
        ) from exc
