import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_platform_admin
from app.api.pagination import Page, page_params, set_total_count, total_count
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import Collection, Organization, Participant, ParticipantList, User
from app.models.platform import PlatformAdminAudit, StoreSubscription
from app.schemas.admin import (
    PlatformAdminSummary,
    PlatformCustomerDetailRead,
    PlatformCustomerRead,
    PlatformCustomerUpdate,
    PlatformCustomerUserRead,
    PlatformGrantProRequest,
    PlatformSubscriptionRead,
)
from app.services.billing import (
    ENTITLED_STATUSES,
    PRO_PRODUCT_ID,
    active_entitlement_subscription,
    subscription_is_entitled,
)

router = APIRouter(prefix="/admin", tags=["platform-admin"])


async def _admin_org_ids(session: AsyncSession) -> set[UUID]:
    """Organizations of platform administrators: not customers."""
    admin_emails = sorted(settings.platform_admin_emails)
    if not admin_emails:
        return set()
    return set(
        (
            await session.execute(
                select(User.organization_id).where(func.lower(User.email).in_(admin_emails))
            )
        ).scalars().all()
    )


def _customer_organizations(admin_org_ids: set[UUID]):
    statement = select(Organization)
    if admin_org_ids:
        statement = statement.where(Organization.id.not_in(admin_org_ids))
    return statement


async def _customer_rows(
    session: AsyncSession,
    *,
    organization_ids: list[UUID] | None = None,
    page: Page | None = None,
) -> tuple[list[PlatformCustomerRead], int]:
    """Customer rows for one page (or for the given organizations) and the total.

    Every aggregate is restricted to the organizations of the page, so the cost is
    bounded by the page size rather than by the number of customers.
    """
    statement = _customer_organizations(await _admin_org_ids(session))
    if organization_ids is not None:
        statement = statement.where(Organization.id.in_(organization_ids))
    total = await total_count(session, statement)
    statement = statement.order_by(Organization.created_at.desc(), Organization.id)
    if page is not None:
        statement = page.apply(statement)
    organizations = (await session.execute(statement)).scalars().all()
    ids = [organization.id for organization in organizations]
    if not ids:
        return [], total

    users = (
        await session.execute(
            select(User).where(User.organization_id.in_(ids)).order_by(User.created_at)
        )
    ).scalars().all()

    list_counts = dict(
        (
            await session.execute(
                select(ParticipantList.organization_id, func.count(ParticipantList.id))
                .where(ParticipantList.organization_id.in_(ids))
                .group_by(ParticipantList.organization_id)
            )
        ).all()
    )
    participant_counts = dict(
        (
            await session.execute(
                select(ParticipantList.organization_id, func.count(Participant.id))
                .join(Participant, Participant.list_id == ParticipantList.id)
                .where(ParticipantList.organization_id.in_(ids))
                .group_by(ParticipantList.organization_id)
            )
        ).all()
    )
    collection_counts = dict(
        (
            await session.execute(
                select(Collection.organization_id, func.count(Collection.id))
                .where(Collection.organization_id.in_(ids))
                .group_by(Collection.organization_id)
            )
        ).all()
    )
    subscriptions = (
        await session.execute(
            select(StoreSubscription)
            .where(
                StoreSubscription.organization_id.in_(ids),
                StoreSubscription.status.in_(ENTITLED_STATUSES),
            )
            .order_by(StoreSubscription.expires_at.desc().nullsfirst())
        )
    ).scalars().all()

    users_by_org: dict[UUID, list[User]] = {}
    for user in users:
        users_by_org.setdefault(user.organization_id, []).append(user)
    subscription_by_org: dict[UUID, StoreSubscription] = {}
    now = datetime.now(UTC)
    for subscription in subscriptions:
        if not subscription_is_entitled(subscription, now=now):
            continue
        subscription_by_org.setdefault(subscription.organization_id, subscription)

    result: list[PlatformCustomerRead] = []
    for organization in organizations:
        org_users = users_by_org.get(organization.id, [])
        subscription = subscription_by_org.get(organization.id)
        primary = org_users[0] if org_users else None
        last_login = max(
            (u.last_login_at for u in org_users if u.last_login_at is not None),
            default=None,
        )
        result.append(
            PlatformCustomerRead(
                organization_id=str(organization.id),
                organization_name=organization.name,
                created_at=organization.created_at,
                locale=organization.locale,
                currency=organization.currency,
                api_enabled=organization.api_enabled,
                plan="pro" if subscription else "free",
                billing_provider=subscription.provider if subscription else None,
                subscription_status=subscription.status if subscription else None,
                subscription_expires_at=subscription.expires_at if subscription else None,
                user_count=len(org_users),
                active_user_count=sum(1 for user in org_users if user.is_active),
                primary_email=primary.email if primary else None,
                last_login_at=last_login,
                participant_lists=int(list_counts.get(organization.id, 0)),
                participants=int(participant_counts.get(organization.id, 0)),
                collections=int(collection_counts.get(organization.id, 0)),
            )
        )
    return result, total


async def _customer_row(session: AsyncSession, organization_id: UUID) -> PlatformCustomerRead | None:
    rows, _total = await _customer_rows(session, organization_ids=[organization_id])
    return rows[0] if rows else None


async def _customer_detail(
    session: AsyncSession,
    organization_id: UUID,
) -> PlatformCustomerDetailRead | None:
    summary_row = await _customer_row(session, organization_id)
    if summary_row is None:
        return None

    users = (
        await session.execute(
            select(User)
            .where(User.organization_id == organization_id)
            .order_by(User.created_at)
        )
    ).scalars().all()
    subscriptions = (
        await session.execute(
            select(StoreSubscription)
            .where(StoreSubscription.organization_id == organization_id)
            .order_by(StoreSubscription.created_at.desc())
        )
    ).scalars().all()

    return PlatformCustomerDetailRead(
        **summary_row.model_dump(),
        users=[
            PlatformCustomerUserRead(
                id=str(user.id),
                email=user.email,
                display_name=user.display_name,
                is_active=user.is_active,
                email_verified=user.email_verified_at is not None,
                created_at=user.created_at,
                last_login_at=user.last_login_at,
            )
            for user in users
        ],
        subscriptions=[
            PlatformSubscriptionRead(
                id=str(subscription.id),
                provider=subscription.provider,
                product_id=subscription.product_id,
                status=subscription.status,
                external_reference=subscription.external_reference,
                purchased_at=subscription.purchased_at,
                expires_at=subscription.expires_at,
                cancelled_at=subscription.cancelled_at,
                auto_renew=subscription.auto_renew,
                environment=subscription.environment,
                last_verified_at=subscription.last_verified_at,
                created_at=subscription.created_at,
                updated_at=subscription.updated_at,
            )
            for subscription in subscriptions
        ],
    )


@router.get("/summary", response_model=PlatformAdminSummary)
async def summary(
    _: User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> PlatformAdminSummary:
    admin_org_ids = await _admin_org_ids(session)
    customers = await total_count(session, _customer_organizations(admin_org_ids))
    active_users_statement = select(func.count(User.id)).where(User.is_active.is_(True))
    if admin_org_ids:
        active_users_statement = active_users_statement.where(User.organization_id.not_in(admin_org_ids))
    active_users = int(await session.scalar(active_users_statement) or 0)
    # Only paying organizations have entitled subscriptions: a small set, checked
    # with the same rule as everywhere else.
    now = datetime.now(UTC)
    entitled = (
        await session.execute(
            select(StoreSubscription).where(StoreSubscription.status.in_(ENTITLED_STATUSES))
        )
    ).scalars().all()
    pro_customers = len(
        {
            subscription.organization_id
            for subscription in entitled
            if subscription.organization_id not in admin_org_ids
            and subscription_is_entitled(subscription, now=now)
        }
    )
    return PlatformAdminSummary(
        customers=customers,
        free_customers=customers - pro_customers,
        pro_customers=pro_customers,
        active_users=active_users,
    )


@router.get("/customers", response_model=list[PlatformCustomerRead])
async def customers(
    response: Response,
    page: Page = Depends(page_params),
    _: User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> list[PlatformCustomerRead]:
    rows, total = await _customer_rows(session, page=page)
    set_total_count(response, total)
    return rows


@router.get("/customers/{organization_id}", response_model=PlatformCustomerDetailRead)
async def customer_detail(
    organization_id: UUID,
    _: User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> PlatformCustomerDetailRead:
    item = await _customer_detail(session, organization_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return item


@router.patch("/customers/{organization_id}", response_model=PlatformCustomerRead)
async def update_customer(
    organization_id: UUID,
    payload: PlatformCustomerUpdate,
    admin: User = Depends(require_platform_admin),
) -> PlatformCustomerRead:
    async with SessionLocal.begin() as session:
        organization = await session.get(Organization, organization_id, with_for_update=True)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        changes: dict[str, object] = {}
        if payload.organization_name is not None:
            name = " ".join(payload.organization_name.split()).strip()
            if name and name != organization.name:
                changes["organization_name"] = {"from": organization.name, "to": name}
                organization.name = name
        if payload.api_enabled is not None and payload.api_enabled != organization.api_enabled:
            changes["api_enabled"] = {
                "from": organization.api_enabled,
                "to": payload.api_enabled,
            }
            organization.api_enabled = payload.api_enabled
        if changes:
            session.add(
                PlatformAdminAudit(
                    admin_user_id=admin.id,
                    organization_id=organization.id,
                    action="customer.update",
                    details_json=json.dumps(changes, ensure_ascii=False),
                )
            )
    async with SessionLocal() as session:
        item = await _customer_row(session, organization_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        return item


@router.post("/customers/{organization_id}/grant-pro", response_model=PlatformCustomerRead)
async def grant_pro(
    organization_id: UUID,
    payload: PlatformGrantProRequest,
    admin: User = Depends(require_platform_admin),
) -> PlatformCustomerRead:
    async with SessionLocal.begin() as session:
        organization = await session.get(Organization, organization_id, with_for_update=True)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        current = await active_entitlement_subscription(session, organization.id)
        if current is not None and current.provider != "admin":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another billing provider already grants Pro for this account",
            )
        subscription = await session.scalar(
            select(StoreSubscription)
            .where(
                StoreSubscription.organization_id == organization.id,
                StoreSubscription.provider == "admin",
            )
            .with_for_update()
        )
        if subscription is None:
            subscription = StoreSubscription(
                organization_id=organization.id,
                provider="admin",
                product_id=PRO_PRODUCT_ID,
                status="active",
            )
            session.add(subscription)
        subscription.status = "active"
        subscription.expires_at = payload.expires_at
        subscription.cancelled_at = None
        subscription.auto_renew = False
        subscription.last_verified_at = datetime.now(UTC)
        session.add(
            PlatformAdminAudit(
                admin_user_id=admin.id,
                organization_id=organization.id,
                action="subscription.grant_pro",
                details_json=json.dumps(
                    {"expires_at": payload.expires_at.isoformat() if payload.expires_at else None}
                ),
            )
        )
    async with SessionLocal() as session:
        item = await _customer_row(session, organization_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        return item


@router.post("/customers/{organization_id}/revoke-admin-pro", response_model=PlatformCustomerRead)
async def revoke_admin_pro(
    organization_id: UUID,
    admin: User = Depends(require_platform_admin),
) -> PlatformCustomerRead:
    async with SessionLocal.begin() as session:
        organization = await session.get(Organization, organization_id, with_for_update=True)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        subscription = await session.scalar(
            select(StoreSubscription)
            .where(
                StoreSubscription.organization_id == organization_id,
                StoreSubscription.provider == "admin",
            )
            .with_for_update()
        )
        if subscription is not None:
            now = datetime.now(UTC)
            subscription.status = "revoked"
            subscription.expires_at = now
            subscription.cancelled_at = now
            subscription.auto_renew = False
            subscription.last_verified_at = now
            session.add(
                PlatformAdminAudit(
                    admin_user_id=admin.id,
                    organization_id=organization_id,
                    action="subscription.revoke_admin_pro",
                    details_json="{}",
                )
            )
    async with SessionLocal() as session:
        item = await _customer_row(session, organization_id)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        return item
