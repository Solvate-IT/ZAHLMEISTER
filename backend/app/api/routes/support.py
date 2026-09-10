import json

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_auth_session
from app.db.session import SessionLocal
from app.models.entities import AuthSession
from app.models.platform import PlatformAdminAudit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/support-logout", status_code=status.HTTP_204_NO_CONTENT)
async def support_logout(
    request: Request,
    auth_session: AuthSession = Depends(get_current_auth_session),
) -> None:
    claims = getattr(request.state, "support_session", None)
    if claims is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Support session required")

    async with SessionLocal.begin() as session:
        stored = await session.get(AuthSession, auth_session.id)
        if stored is not None:
            await session.delete(stored)
        session.add(
            PlatformAdminAudit(
                admin_user_id=claims.admin_user_id,
                organization_id=claims.organization_id,
                action="support.impersonation_end",
                details_json=json.dumps(
                    {
                        "target_user_id": str(claims.user_id),
                        "read_only": True,
                    },
                    separators=(",", ":"),
                ),
            )
        )
