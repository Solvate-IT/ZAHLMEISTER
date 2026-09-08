from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import AuthSession, Organization, User
from app.services.auth import hash_password, normalize_email, verify_password


def _insecure_bootstrap_password(password: str) -> bool:
    lowered = password.strip().lower()
    return not password.strip() or "change-me" in lowered or len(password) < 16


async def bootstrap_platform_admin() -> None:
    email = normalize_email(settings.platform_admin_bootstrap_email)
    password = settings.platform_admin_bootstrap_password
    if not email or not password:
        return
    if email not in settings.platform_admin_emails:
        raise RuntimeError("PLATFORM_ADMIN_BOOTSTRAP_EMAIL must be listed in PLATFORM_ADMIN_EMAILS")

    async with SessionLocal.begin() as session:
        existing = await session.scalar(select(User).where(User.email == email).with_for_update())
        if _insecure_bootstrap_password(password):
            if existing is not None and verify_password(existing.password_hash, password):
                existing.is_active = False
                await session.execute(delete(AuthSession).where(AuthSession.user_id == existing.id))
            return
        if existing is not None:
            return
        organization = Organization(
            name=settings.platform_admin_bootstrap_name or "Zahlmeister Administration",
            locale="de-AT",
            currency="EUR",
        )
        session.add(organization)
        await session.flush()
        session.add(
            User(
                organization_id=organization.id,
                email=email,
                display_name=settings.platform_admin_bootstrap_name or "Zahlmeister Administration",
                password_hash=hash_password(password),
                email_verified_at=datetime.now(UTC),
            )
        )


async def set_platform_admin_password(email: str, password: str) -> None:
    normalized = normalize_email(email)
    if normalized not in settings.platform_admin_emails:
        raise RuntimeError("Platform admin email must be listed in PLATFORM_ADMIN_EMAILS")
    if _insecure_bootstrap_password(password):
        raise ValueError("Platform admin password must be at least 16 characters and not a placeholder")

    async with SessionLocal.begin() as session:
        user = await session.scalar(select(User).where(User.email == normalized).with_for_update())
        if user is None:
            organization = Organization(
                name=settings.platform_admin_bootstrap_name or "Zahlmeister Administration",
                locale="de-AT",
                currency="EUR",
            )
            session.add(organization)
            await session.flush()
            user = User(
                organization_id=organization.id,
                email=normalized,
                display_name=settings.platform_admin_bootstrap_name or "Zahlmeister Administration",
                password_hash=hash_password(password),
                email_verified_at=datetime.now(UTC),
                is_active=True,
            )
            session.add(user)
            await session.flush()
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
            if user.email_verified_at is None:
                user.email_verified_at = datetime.now(UTC)

        await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
