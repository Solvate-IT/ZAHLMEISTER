from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models.platform import StoreSubscription
from app.services.billing import PRO_PRODUCT_ID, subscription_is_entitled


def _subscription(*, status: str, expires_at=None) -> StoreSubscription:
    return StoreSubscription(
        organization_id=uuid4(),
        provider="google",
        product_id=PRO_PRODUCT_ID,
        status=status,
        external_reference=str(uuid4()),
        expires_at=expires_at,
    )


def test_active_subscription_entitles_account() -> None:
    subscription = _subscription(status="active")
    assert subscription_is_entitled(subscription) is True


def test_grace_period_keeps_cross_platform_entitlement() -> None:
    subscription = _subscription(
        status="grace_period",
        expires_at=datetime.now(UTC) + timedelta(days=2),
    )
    assert subscription_is_entitled(subscription) is True


def test_expired_subscription_does_not_entitle_account() -> None:
    subscription = _subscription(
        status="active",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert subscription_is_entitled(subscription) is False


def test_cancelled_subscription_does_not_entitle_account() -> None:
    subscription = _subscription(
        status="cancelled",
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    assert subscription_is_entitled(subscription) is False
