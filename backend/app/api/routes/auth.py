from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_auth_session, get_current_user, get_session
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import AuthSession, Organization, User
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
    auth_response,
    create_auth_session,
    hash_password,
    normalize_email,
    user_read,
    verify_password,
)
from app.services.platform_mail import send_platform_mail

router = APIRouter(prefix="/auth", tags=["auth"])


def _action_url(action: str, token: str) -> str:
    base = settings.public_app_url.rstrip("/")
    return f"{base}/?action={action}&token={token}"


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
            response = auth_response(token, user, organization)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc

    if verification_token:
        background_tasks.add_task(_send_verification, email, verification_token, payload.locale)
    return response


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest) -> AuthResponse:
    email = normalize_email(str(payload.email))
    async with SessionLocal.begin() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if (
            user is None
            or not user.is_active
            or not verify_password(user.password_hash, payload.password)
        ):
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
    async with SessionLocal.begin() as session:
        user = await consume_action_token(session, payload.token, RESET_PURPOSE)
        if user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
        user.password_hash = hash_password(payload.new_password)
        await invalidate_user_sessions(session, user.id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    auth_session: AuthSession = Depends(get_current_auth_session),
) -> None:
    async with SessionLocal.begin() as session:
        stored = await session.get(AuthSession, auth_session.id)
        if stored is not None:
            await session.delete(stored)
