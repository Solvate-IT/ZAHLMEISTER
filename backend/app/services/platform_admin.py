from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import Organization, User
from app.services.auth import hash_password, normalize_email


async def bootstrap_platform_admin() -> None:
    email = normalize_email(settings.platform_admin_bootstrap_email)
    password = settings.platform_admin_bootstrap_password
    if not email or not password:
        return
    if email not in settings.platform_admin_emails:
        raise RuntimeError("PLATFORM_ADMIN_BOOTSTRAP_EMAIL must be listed in PLATFORM_ADMIN_EMAILS")

    async with SessionLocal.begin() as session:
        existing = await session.scalar(select(User).where(User.email == email))
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
