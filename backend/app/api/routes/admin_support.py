import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import require_platform_admin
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import Organization, User
from app.models.platform import PlatformAdminAudit
from app.schemas.admin import PlatformSupportSessionCreate, PlatformSupportSessionRead
from app.services.auth import is_platform_admin
from app.services.support_sessions import SUPPORT_SESSION_MINUTES, create_support_session

router = APIRouter(prefix="/admin", tags=["platform-admin"])


@router.post(
    "/customers/{organization_id}/users/{user_id}/support-session",
    response_model=PlatformSupportSessionRead,
)
async def create_customer_support_session(
    organization_id: UUID,
    user_id: UUID,
    payload: PlatformSupportSessionCreate,
    admin: User = Depends(require_platform_admin),
) -> PlatformSupportSessionRead:
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A support reason is required",
        )

    async with SessionLocal.begin() as session:
        organization = await session.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer user not found")
        organization_emails = list(
            await session.scalars(select(User.email).where(User.organization_id == organization_id))
        )
        if any(email.casefold() in settings.platform_admin_emails for email in organization_emails):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer user not found")

        target_user = await session.scalar(
            select(User).where(
                User.id == user_id,
                User.organization_id == organization_id,
                User.is_active.is_(True),
            )
        )
        if target_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer user not found")
        if is_platform_admin(target_user):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Platform administrators cannot be opened as support sessions",
            )

        access_token, _, claims = await create_support_session(
            session,
            target_user=target_user,
            admin_user=admin,
        )
        session.add(
            PlatformAdminAudit(
                admin_user_id=admin.id,
                organization_id=organization.id,
                action="support.impersonation_start",
                details_json=json.dumps(
                    {
                        "target_user_id": str(target_user.id),
                        "reason": reason,
                        "read_only": True,
                        "expires_at": claims.expires_at.isoformat(),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        return PlatformSupportSessionRead(
            access_token=access_token,
            expires_in=SUPPORT_SESSION_MINUTES * 60,
            expires_at=claims.expires_at,
            user_id=str(target_user.id),
            user_name=target_user.display_name,
            user_email=target_user.email,
            organization_id=str(organization.id),
            organization_name=organization.name,
        )
