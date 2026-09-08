import logging
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.db.session import SessionLocal
from app.models.billing import BillingInvoice, BillingProfile
from app.models.entities import User
from app.schemas.billing import (
    BillingEntitlementRead,
    BillingInvoiceRead,
    BillingProfileRead,
    BillingProfileWrite,
    BillingPurchaseContextRead,
    MollieBillingCheckoutRead,
    MollieBillingConfigRead,
)
from app.services.billing import Entitlement, entitlement_for_organization, purchase_context
from app.services.billing_tax import (
    BillingTaxInvalidVatNumber,
    BillingTaxUnsupportedJurisdiction,
    BillingTaxValidationUnavailable,
)
from app.services.mollie_billing import (
    MollieBillingConflict,
    MollieBillingProfileRequired,
    MollieBillingUnavailable,
    MollieBillingVerificationError,
    billing_config,
    cancel_subscription,
    process_payment,
    start_checkout,
    sync_subscription,
)

logger = logging.getLogger(__name__)
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


def _profile_read(item: BillingProfile) -> BillingProfileRead:
    return BillingProfileRead(
        customer_type=item.customer_type,
        given_name=item.given_name,
        family_name=item.family_name,
        organization_name=item.organization_name,
        billing_email=item.billing_email,
        street_and_number=item.street_and_number,
        postal_code=item.postal_code,
        city=item.city,
        region=item.region,
        country=item.country,
        vat_number=item.vat_number,
        organization_number=item.organization_number,
        vat_validation_status=item.vat_validation_status,
        vat_validated_at=item.vat_validated_at,
    )


def _invoice_read(item: BillingInvoice) -> BillingInvoiceRead:
    return BillingInvoiceRead(
        id=str(item.id),
        provider=item.provider,
        product_id=item.product_id,
        tariff_version=item.tariff_version,
        period_start=item.period_start,
        period_end=item.period_end,
        gross_amount=f"{Decimal(item.gross_amount):.2f}",
        currency=item.currency,
        vat_rate=f"{Decimal(item.vat_rate):.2f}",
        vat_scheme=item.vat_scheme,
        tax_treatment=item.tax_treatment,
        invoice_number=item.invoice_number,
        status=item.status,
        payment_url=item.payment_url,
        paid_at=item.paid_at,
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


@router.get("/profile", response_model=BillingProfileRead | None)
async def billing_profile(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BillingProfileRead | None:
    item = await session.get(BillingProfile, user.organization_id)
    return _profile_read(item) if item is not None else None


@router.put("/profile", response_model=BillingProfileRead)
async def save_billing_profile(
    payload: BillingProfileWrite,
    user: User = Depends(get_current_user),
) -> BillingProfileRead:
    async with SessionLocal.begin() as session:
        item = await session.get(BillingProfile, user.organization_id, with_for_update=True)
        if item is None:
            item = BillingProfile(
                organization_id=user.organization_id,
                customer_type=payload.customer_type,
                billing_email=payload.billing_email,
                street_and_number=payload.street_and_number,
                postal_code=payload.postal_code,
                city=payload.city,
                country=payload.country,
            )
            session.add(item)
        item.customer_type = payload.customer_type
        item.given_name = payload.given_name
        item.family_name = payload.family_name
        item.organization_name = payload.organization_name
        item.billing_email = payload.billing_email
        item.street_and_number = payload.street_and_number
        item.postal_code = payload.postal_code
        item.city = payload.city
        item.region = payload.region
        item.country = payload.country
        item.vat_number = payload.vat_number
        item.organization_number = payload.organization_number
        item.vat_validation_status = "unverified"
        item.vat_validated_at = None
        await session.flush()
        return _profile_read(item)


@router.get("/invoices", response_model=list[BillingInvoiceRead])
async def billing_invoices(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[BillingInvoiceRead]:
    rows = (
        await session.execute(
            select(BillingInvoice)
            .where(BillingInvoice.organization_id == user.organization_id)
            .order_by(BillingInvoice.period_start.desc(), BillingInvoice.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return [_invoice_read(item) for item in rows]


@router.get("/mollie/config", response_model=MollieBillingConfigRead)
async def mollie_config(_: User = Depends(get_current_user)) -> MollieBillingConfigRead:
    return MollieBillingConfigRead.model_validate(billing_config())


@router.post("/mollie/checkout", response_model=MollieBillingCheckoutRead)
async def mollie_checkout(user: User = Depends(get_current_user)) -> MollieBillingCheckoutRead:
    try:
        async with SessionLocal.begin() as session:
            item = await start_checkout(session, user.organization_id)
    except (MollieBillingProfileRequired, BillingTaxInvalidVatNumber, BillingTaxUnsupportedJurisdiction) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except BillingTaxValidationUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tax validation is temporarily unavailable",
        ) from exc
    except MollieBillingConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MollieBillingUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mollie billing is unavailable",
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
            detail="The Mollie billing state could not be verified",
        ) from exc
    except (BillingTaxInvalidVatNumber, BillingTaxUnsupportedJurisdiction) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (BillingTaxValidationUnavailable, MollieBillingUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing verification is temporarily unavailable",
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
            detail="Mollie billing is unavailable",
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
        logger.warning("Rejected unverifiable Mollie billing webhook")
        return
    except MollieBillingUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing verification temporarily unavailable",
        ) from exc
