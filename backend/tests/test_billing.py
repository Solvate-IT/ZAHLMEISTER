from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models.platform import StoreSubscription
from app.services.billing import (
    PRO_PRODUCT_ID,
    VerifiedSubscription,
    _preserve_cancelled_state,
    subscription_is_entitled,
    validate_verified_subscription,
    verified_subscription_is_entitled,
)


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


def test_cancelled_subscription_stays_entitled_until_paid_period_ends() -> None:
    subscription = _subscription(
        status="cancelled",
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    assert subscription_is_entitled(subscription) is True


def test_cancelled_subscription_stops_entitlement_after_paid_period() -> None:
    subscription = _subscription(
        status="cancelled",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert subscription_is_entitled(subscription) is False


def test_cancelled_subscription_without_expiry_never_entitles_account() -> None:
    subscription = _subscription(status="cancelled")
    assert subscription_is_entitled(subscription) is False


def test_verified_active_purchase_is_entitled() -> None:
    organization_id = uuid4()
    verified = VerifiedSubscription(
        provider="google",
        product_id=PRO_PRODUCT_ID,
        external_reference="purchase-token",
        account_token=str(organization_id),
        status="active",
    )
    assert verified_subscription_is_entitled(verified) is True


def test_verified_cancelled_purchase_is_only_entitled_until_expiry() -> None:
    organization_id = uuid4()
    verified = VerifiedSubscription(
        provider="apple",
        product_id=PRO_PRODUCT_ID,
        external_reference="original-transaction-id",
        account_token=str(organization_id),
        status="cancelled",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert verified_subscription_is_entitled(verified) is False


def test_verified_purchase_must_be_bound_to_same_organization() -> None:
    organization_id = uuid4()
    verified = VerifiedSubscription(
        provider="apple",
        product_id=PRO_PRODUCT_ID,
        external_reference="original-transaction-id",
        account_token=str(uuid4()),
        status="active",
    )
    with pytest.raises(ValueError, match="another Zahlmeister account"):
        validate_verified_subscription(organization_id, verified)


def test_verified_purchase_rejects_wrong_product() -> None:
    organization_id = uuid4()
    verified = VerifiedSubscription(
        provider="google",
        product_id="other.product",
        external_reference="purchase-token",
        account_token=str(organization_id),
        status="active",
    )
    with pytest.raises(ValueError, match="Unexpected billing product"):
        validate_verified_subscription(organization_id, verified)


def test_late_paid_event_does_not_undo_existing_cancellation() -> None:
    organization_id = uuid4()
    subscription = StoreSubscription(
        organization_id=organization_id,
        provider="mollie",
        product_id=PRO_PRODUCT_ID,
        status="cancelled",
        external_reference="invoice_old",
        auto_renew=False,
        cancelled_at=datetime.now(UTC) - timedelta(minutes=5),
        expires_at=datetime.now(UTC) + timedelta(days=10),
    )
    verified = VerifiedSubscription(
        provider="mollie",
        product_id=PRO_PRODUCT_ID,
        external_reference="invoice_new",
        account_token=str(organization_id),
        status="active",
        expires_at=datetime.now(UTC) + timedelta(days=365),
        auto_renew=False,
    )

    assert _preserve_cancelled_state(subscription, verified) is True


def test_explicit_provider_reactivation_may_enable_auto_renew_again() -> None:
    organization_id = uuid4()
    subscription = StoreSubscription(
        organization_id=organization_id,
        provider="mollie",
        product_id=PRO_PRODUCT_ID,
        status="cancelled",
        external_reference="invoice_old",
        auto_renew=False,
        cancelled_at=datetime.now(UTC) - timedelta(minutes=5),
        expires_at=datetime.now(UTC) + timedelta(days=10),
    )
    verified = VerifiedSubscription(
        provider="mollie",
        product_id=PRO_PRODUCT_ID,
        external_reference="mandate_reactivated",
        account_token=str(organization_id),
        status="active",
        expires_at=datetime.now(UTC) + timedelta(days=365),
        auto_renew=True,
    )

    assert _preserve_cancelled_state(subscription, verified) is False
