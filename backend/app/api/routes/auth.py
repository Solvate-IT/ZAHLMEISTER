import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_admin_auth_session,
    get_current_auth_session,
    get_current_user,
    get_session,
    require_platform_admin,
)
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import AuthSession, Organization, User
from app.models.platform import PlatformAdminAudit
from app.schemas.account import ForgotPasswordRequest, ResetPasswordRequest, TokenRequest
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserRead
from app.services.account import (
    RESET_PURPOSE,
    VERIFY_PURPOSE,
    consume_action_token,
    create_action_token,
    invalidate_user_sessions,
)
from app.services.account_mail import password_reset_mail, verification_mail
from app.services.auth import (
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_HOURS,
    ADMIN_TOKEN_PREFIX,
    auth_response,
    create_auth_session,
    hash_password,
    is_platform_admin,
    normalize_email,
    user_read,
    verify_missing_user_password,
    verify_password,
)
from app.services.platform_mail import send_platform_mail

router = APIRouter(prefix="/auth", tags=["auth"])

ADMIN_LOGIN_FAILURE_LIMIT = 5
ADMIN_LOGIN_WINDOW_MINUTES = 15


def _action_url(action: str, token: str) -> str:
    base = settings.public_app_url.rstrip("/")
    return f"{base}/?action={action}&token={token}"


def _admin_attempt_details(email: str) -> str:
    email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()
    return json.dumps({"email_hash": email_hash}, separators=(",", ":"))


async def _send_verification(email: str, token: str, locale: str) -> None:
    subject, body = verification_mail(locale, _action_url("verify-email", token))
    await send_platform_mail(recipient=email, subject=subject, body=body)


async def _send_password_reset(email: str, token: str, locale: str) -> None:
    subject, body = password_reset_mail(locale, _action_url("reset-password", token))
    await send_platform_mail(recipient=email, subject=subject, body=body)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, background_tasks: BackgroundTasks) -> AuthResponse:
    email = normalize_email(str(payload.email))
    if email in settings.platform_admin_emails:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reserved account")
    verification_token: str | None = None
    try:
        async with SessionLocal.begin() as session:
            existing = await session.scalar(select(User.id).where(User.email == email))
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
                )

            display_name = payload.display_name or email.split("@", maxsplit=1)[0]
            organization = Organization(
                name=display_name,
                locale=payload.locale,
                currency=payload.currency,
            )
            session.add(organization)
            await session.flush()

            user = User(
                organization_id=organization.id,
                email=email,
                display_name=display_name,
                password_hash=hash_password(payload.password),
            )
            session.add(user)
            await session.flush()
            verification_token = await create_action_token(
                session, user, VERIFY_PURPOSE, ttl=timedelta(hours=24)
            )
            token = await create_auth_session(session, user)
            result = auth_response(token, user, organization)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc

    if verification_token:
        background_tasks.add_task(_send_verification, email, verification_token, payload.locale)
    return result


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest) -> AuthResponse:
    email = normalize_email(str(payload.email))
    if email in settings.platform_admin_emails:
        async with SessionLocal() as session:
            user = await session.scalar(select(User).where(User.email == email))
            if user is None:
                verify_missing_user_password(payload.password)
            else:
                verify_password(user.password_hash, payload.password)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    async with SessionLocal.begin() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            verify_missing_user_password(payload.password)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        if not user.is_active or not verify_password(user.password_hash, payload.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        organization = await session.get(Organization, user.organization_id)
        if organization is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable"
            )
        user.last_login_at = datetime.now(UTC)
        token = await create_auth_session(session, user)
        return auth_response(token, user, organization)


@router.post("/admin-login", response_model=UserRead)
async def admin_login(payload: LoginRequest, response: Response) -> UserRead:
    email = normalize_email(str(payload.email))
    now = datetime.now(UTC)
    details = _admin_attempt_details(email)
    result: UserRead | None = None
    admin_token: str | None = None
    denied = False

    async with SessionLocal.begin() as session:
        recent_failures = int(
            await session.scalar(
                select(func.count())
                .select_from(PlatformAdminAudit)
                .where(
                    PlatformAdminAudit.action == "auth.admin_login_failed",
                    PlatformAdminAudit.details_json == details,
                    PlatformAdminAudit.created_at
                    > now - timedelta(minutes=ADMIN_LOGIN_WINDOW_MINUTES),
                )
            )
            or 0
        )
        throttled = recent_failures >= ADMIN_LOGIN_FAILURE_LIMIT
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            verify_missing_user_password(payload.password)
            valid = False
        else:
            valid = is_platform_admin(user) and verify_password(user.password_hash, payload.password)

        if throttled or not valid or user is None:
            denied = True
            if not throttled:
                session.add(
                    PlatformAdminAudit(
                        action="auth.admin_login_failed",
                        details_json=details,
                    )
                )
        else:
            organization = await session.get(Organization, user.organization_id)
            if organization is None:
                denied = True
                session.add(
                    PlatformAdminAudit(
                        action="auth.admin_login_failed",
                        details_json=details,
                    )
                )
            else:
                user.last_login_at = now
                admin_token = await create_auth_session(
                    session,
                    user,
                    ttl=timedelta(hours=ADMIN_SESSION_HOURS),
                    token_prefix=ADMIN_TOKEN_PREFIX,
                )
                session.add(
                    PlatformAdminAudit(
                        admin_user_id=user.id,
                        organization_id=user.organization_id,
                        action="auth.admin_login_success",
                        details_json="{}",
                    )
                )
                result = user_read(user, organization)

    if denied or result is None or admin_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=admin_token,
        max_age=ADMIN_SESSION_HOURS * 3600,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        path="/api/v1",
    )
    return result


@router.get("/admin-me", response_model=UserRead)
async def admin_me(
    admin: User = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    organization = await session.get(Organization, admin.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return user_read(admin, organization)


@router.post("/admin-logout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_logout(
    response: Response,
    auth_session: AuthSession = Depends(get_current_admin_auth_session),
    _: User = Depends(require_platform_admin),
) -> None:
    async with SessionLocal.begin() as session:
        stored = await session.get(AuthSession, auth_session.id)
        if stored is not None:
            await session.delete(stored)
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE,
        path="/api/v1",
        secure=settings.environment == "production",
        httponly=True,
        samesite="strict",
    )


@router.get("/me", response_model=UserRead)
async def me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserRead:
    organization = await session.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return user_read(user, organization)


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
async def resend_verification(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> None:
    if user.email_verified_at is not None:
        return
    async with SessionLocal.begin() as session:
        stored = await session.get(User, user.id)
        if stored is None:
            return
        token = await create_action_token(
            session, stored, VERIFY_PURPOSE, ttl=timedelta(hours=24)
        )
        email = stored.email
        organization = await session.get(Organization, stored.organization_id)
        locale = organization.locale if organization is not None else "en"
    background_tasks.add_task(_send_verification, email, token, locale)


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(payload: TokenRequest) -> None:
    async with SessionLocal.begin() as session:
        user = await consume_action_token(session, payload.token, VERIFY_PURPOSE)
        if user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
        user.email_verified_at = datetime.now(UTC)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
) -> None:
    email = normalize_email(payload.email)
    if email in settings.platform_admin_emails:
        return
    token: str | None = None
    locale = "en"
    async with SessionLocal.begin() as session:
        user = await session.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
        if user is not None:
            token = await create_action_token(
                session, user, RESET_PURPOSE, ttl=timedelta(minutes=60)
            )
            organization = await session.get(Organization, user.organization_id)
            if organization is not None:
                locale = organization.locale
    if token is not None:
        background_tasks.add_task(_send_password_reset, email, token, locale)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(payload: ResetPasswordRequest) -> None:
    admin_reset_denied = False
    async with SessionLocal.begin() as session:
        user = await consume_action_token(session, payload.token, RESET_PURPOSE)
        if user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
        if user.email.casefold() in settings.platform_admin_emails:
            admin_reset_denied = True
        else:
            user.password_hash = hash_password(payload.new_password)
            await invalidate_user_sessions(session, user.id)
    if admin_reset_denied:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    auth_session: AuthSession = Depends(get_current_auth_session),
) -> None:
    async with SessionLocal.begin() as session:
        stored = await session.get(AuthSession, auth_session.id)
        if stored is not None:
            await session.delete(stored)
