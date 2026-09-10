import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.services.google_play_billing import (
    GOOGLE_PLAY_BASE_PLAN_ID,
    GOOGLE_PLAY_PACKAGE_NAME,
    GOOGLE_PLAY_PRODUCT_ID,
    GooglePlayBillingVerificationError,
    _purchase_reference,
    decode_rtdn_payload,
    verified_subscription_from_google,
)


def _purchase_payload(
    organization_id,
    *,
    state="SUBSCRIPTION_STATE_ACTIVE",
    auto_renew=True,
    product_id=GOOGLE_PLAY_PRODUCT_ID,
):
    expires_at = datetime.now(UTC) + timedelta(days=365)
    return {
        "subscriptionState": state,
        "startTime": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "externalAccountIdentifiers": {
            "obfuscatedExternalAccountId": str(organization_id),
        },
        "lineItems": [
            {
                "productId": product_id,
                "expiryTime": expires_at.isoformat().replace("+00:00", "Z"),
                "autoRenewingPlan": {"autoRenewEnabled": auto_renew},
            }
        ],
    }


def test_google_play_catalog_contract_matches_android_package() -> None:
    assert GOOGLE_PLAY_PACKAGE_NAME == "at.solvate.zahlmeister"
    assert GOOGLE_PLAY_PRODUCT_ID == "zahlmeister.pro.yearly"
    assert GOOGLE_PLAY_BASE_PLAN_ID == "yearly"


def test_active_google_subscription_maps_to_shared_entitlement() -> None:
    organization_id = uuid4()
    verified = verified_subscription_from_google(
        organization_id,
        "secret-purchase-token",
        _purchase_payload(organization_id),
        require_account_match=True,
    )

    assert verified.provider == "google"
    assert verified.product_id == GOOGLE_PLAY_PRODUCT_ID
    assert verified.account_token == str(organization_id)
    assert verified.status == "active"
    assert verified.auto_renew is True
    assert verified.expires_at is not None
    assert verified.external_reference.startswith("google:")
    assert "secret-purchase-token" not in verified.external_reference
    assert verified.verification_data == {"purchase_token": "secret-purchase-token"}


def test_cancelled_google_subscription_remains_identifiable_until_expiry() -> None:
    organization_id = uuid4()
    verified = verified_subscription_from_google(
        organization_id,
        "cancelled-token",
        _purchase_payload(
            organization_id,
            state="SUBSCRIPTION_STATE_CANCELED",
            auto_renew=False,
        ),
        require_account_match=True,
    )

    assert verified.status == "cancelled"
    assert verified.auto_renew is False
    assert verified.expires_at is not None


def test_google_purchase_must_be_bound_to_same_zahlmeister_account() -> None:
    organization_id = uuid4()
    with pytest.raises(GooglePlayBillingVerificationError, match="another Zahlmeister account"):
        verified_subscription_from_google(
            organization_id,
            "purchase-token",
            _purchase_payload(uuid4()),
            require_account_match=True,
        )


def test_google_purchase_rejects_unexpected_product() -> None:
    organization_id = uuid4()
    with pytest.raises(GooglePlayBillingVerificationError, match="Unexpected Google Play"):
        verified_subscription_from_google(
            organization_id,
            "purchase-token",
            _purchase_payload(organization_id, product_id="other.product"),
            require_account_match=True,
        )


def test_purchase_reference_is_deterministic_without_exposing_token() -> None:
    first = _purchase_reference("very-secret-token")
    second = _purchase_reference("very-secret-token")
    assert first == second
    assert "very-secret-token" not in first


def test_rtdn_subscription_notification_extracts_purchase_token() -> None:
    notification = {
        "version": "1.0",
        "packageName": GOOGLE_PLAY_PACKAGE_NAME,
        "eventTimeMillis": "0",
        "subscriptionNotification": {
            "version": "1.0",
            "notificationType": 3,
            "purchaseToken": "purchase-token",
            "subscriptionId": GOOGLE_PLAY_PRODUCT_ID,
        },
    }
    payload = {
        "message": {
            "messageId": "message-1",
            "data": base64.b64encode(json.dumps(notification).encode()).decode(),
        }
    }

    assert decode_rtdn_payload(payload) == ("message-1", "purchase-token")


def test_rtdn_test_notification_is_accepted_without_subscription_token() -> None:
    notification = {
        "version": "1.0",
        "packageName": GOOGLE_PLAY_PACKAGE_NAME,
        "eventTimeMillis": "0",
        "testNotification": {"version": "1.0"},
    }
    payload = {
        "message": {
            "messageId": "message-2",
            "data": base64.b64encode(json.dumps(notification).encode()).decode(),
        }
    }

    assert decode_rtdn_payload(payload) == ("message-2", None)


def test_rtdn_rejects_another_android_package() -> None:
    notification = {
        "version": "1.0",
        "packageName": "com.example.other",
        "subscriptionNotification": {
            "purchaseToken": "purchase-token",
        },
    }
    payload = {
        "message": {
            "data": base64.b64encode(json.dumps(notification).encode()).decode(),
        }
    }

    with pytest.raises(GooglePlayBillingVerificationError, match="Unexpected Google Play package"):
        decode_rtdn_payload(payload)
