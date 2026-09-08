import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_platform_admin
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


def _admin_org_ids(rows: list[tuple[UUID, str]]) -> set[UUID]:
    admin_emails = settings.platform_admin_emails
    return {organization_id for organization_id, email in rows if email.casefold() in admin_emails}


async def _customer_rows(session: AsyncSession) -> list[PlatformCustomerRead]:
    organizations = (
        await session.execute(select(Organization).order_by(Organization.created_at.desc()))
    ).scalars().all()
    users = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    admin_org_ids = _admin_org_ids([(user.organization_id, user.email) for user in users])

    list_counts = dict(
        (
            await session.execute(
                select(ParticipantList.organization_id, func.count(ParticipantList.id)).group_by(
                    ParticipantList.organization_id
                )
            )
        ).all()
    )
    participant_counts = dict(
        (
            await session.execute(
                select(ParticipantList.organization_id, func.count(Participant.id))
                .join(Participant, Participant.list_id == ParticipantList.id)
                .group_by(ParticipantList.organization_id)
            )
        ).all()
    )
    collection_counts = dict(
        (
            await session.execute(
                select(Collection.organization_id, func.count(Collection.id)).group_by(
                    Collection.organization_id
                )
            )
        ).all()
    )
    subscriptions = (
        await session.execute(
            select(StoreSubscription)
            .where(StoreSubscription.status.in_(ENTITLED_STATUSES))
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
        if organization.id in admin_org_ids:
            continue
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
    return result


async def _customer_detail(
    session: AsyncSession,
    organization_id: UUID,
) -> PlatformCustomerDetailRead | None:
    summary_row = next(
        (
            item
            for item in await _customer_rows(session)
            if item.organization_id == str(organization_id)
        ),
        None,
    )
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
    customers = await _customer_rows(session)
    return PlatformAdminSummary(
        customers=len(customers),
        free_customers=sum(1 for item in customers if item.plan == "free"),
        pro_customers=sum(1 for item in customers if item.plan == "pro"),
        active_users=sum(item.active_user_count for item in customers),
    )


@router.get("/customers", response_model=list[PlatformCustomerRead])
async def customers(
    _: User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> list[PlatformCustomerRead]:
    return await _customer_rows(session)


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
        rows = await _customer_rows(session)
        item = next((row for row in rows if row.organization_id == str(organization_id)), None)
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
        return next(
            row
            for row in await _customer_rows(session)
            if row.organization_id == str(organization_id)
        )


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
        rows = await _customer_rows(session)
        item = next((row for row in rows if row.organization_id == str(organization_id)), None)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        return item