import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import require_platform_admin
from app.db.session import SessionLocal
from app.models.entities import Organization, User
from app.models.platform import PlatformAdminAudit
from app.services.auth import is_platform_admin
from app.services.support_sessions import SUPPORT_SESSION_MINUTES, create_support_session

router = APIRouter(prefix="/admin", tags=["platform-admin"])


class SupportSessionCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class SupportSessionRead(BaseModel):
    access_token: str
    expires_in: int
    expires_at: str
    user_id: str
    user_name: str
    user_email: str
    organization_id: str
    organization_name: str
    read_only: bool = True


@router.post(
    "/customers/{organization_id}/users/{user_id}/support-session",
    response_model=SupportSessionRead,
)
async def create_customer_support_session(
    organization_id: UUID,
    user_id: UUID,
    payload: SupportSessionCreate,
    admin: User = Depends(require_platform_admin),
) -> SupportSessionRead:
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A support reason is required",
        )

    async with SessionLocal.begin() as session:
        organization = await session.get(Organization, organization_id)
        target_user = await session.scalar(
            select(User).where(
                User.id == user_id,
                User.organization_id == organization_id,
                User.is_active.is_(True),
            )
        )
        if organization is None or target_user is None:
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
        return SupportSessionRead(
            access_token=access_token,
            expires_in=SUPPORT_SESSION_MINUTES * 60,
            expires_at=claims.expires_at.isoformat(),
            user_id=str(target_user.id),
            user_name=target_user.display_name,
            user_email=target_user.email,
            organization_id=str(organization.id),
            organization_name=organization.name,
        )
