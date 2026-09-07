import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AccountActionToken, AuthSession, User
from app.services.auth import token_hash

VERIFY_PURPOSE = "verify_email"
RESET_PURPOSE = "reset_password"


async def create_action_token(
    session: AsyncSession,
    user: User,
    purpose: str,
    *,
    ttl: timedelta,
) -> str:
    locked_user = await session.get(User, user.id, with_for_update=True)
    if locked_user is None:
        raise ValueError("User not found")
    await session.execute(
        delete(AccountActionToken).where(
            AccountActionToken.user_id == user.id,
            AccountActionToken.purpose == purpose,
            AccountActionToken.used_at.is_(None),
        )
    )
    raw = secrets.token_urlsafe(40)
    session.add(
        AccountActionToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=token_hash(raw),
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    await session.flush()
    return raw


async def consume_action_token(
    session: AsyncSession,
    raw_token: str,
    purpose: str,
) -> User | None:
    record = await session.scalar(
        select(AccountActionToken)
        .where(
            AccountActionToken.token_hash == token_hash(raw_token),
            AccountActionToken.purpose == purpose,
            AccountActionToken.used_at.is_(None),
        )
        .with_for_update()
    )
    if record is None or record.expires_at <= datetime.now(UTC):
        return None
    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        return None
    record.used_at = datetime.now(UTC)
    return user


async def invalidate_user_sessions(session: AsyncSession, user_id, *, keep_session_id=None) -> None:
    statement = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep_session_id is not None:
        statement = statement.where(AuthSession.id != keep_session_id)
    await session.execute(statement)
