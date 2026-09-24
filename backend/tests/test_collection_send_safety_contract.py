from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.api.routes import account
from app.models.billing import BillingProfile
from app.models.entities import Organization, User
from app.schemas.account import ProfileUpdateRequest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT.parent / "frontend"


def backend(path: str) -> str:
    return (ROOT / path).read_text()


def frontend(path: str) -> str:
    return (FRONTEND / path).read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phone", "country", "expected"),
    [
        ("0660 1234567", None, "+436601234567"),
        ("030 901820", "DE", "+4930901820"),
        ("", None, None),
    ],
)
async def test_account_phone_is_persisted_and_exposed_for_test_delivery(
    monkeypatch, phone, country, expected,
) -> None:
    organization = Organization(id=uuid4(), name="Test", locale="de-AT", currency="EUR")
    user = User(
        id=uuid4(), organization_id=organization.id, email="anna@example.com",
        display_name="Anna", phone="+436641234567",
    )
    profile = BillingProfile(country=country) if country else None
    session = AsyncMock()
    session.get.side_effect = lambda model, _id: {
        User: user, Organization: organization, BillingProfile: profile,
    }[model]
    factory = MagicMock()
    factory.begin.return_value.__aenter__.return_value = session
    monkeypatch.setattr(account, "SessionLocal", factory)

    result = await account.update_profile(ProfileUpdateRequest(phone=phone), user=user)

    assert user.phone == expected
    assert result.phone == expected
    session.flush.assert_awaited_once()


def test_backend_has_non_mutating_test_delivery_and_real_dispatch_endpoint() -> None:
    communications_schema = backend("app/schemas/communications.py")
    communications_route = backend("app/api/routes/communications.py")
    collections_route = backend("app/api/routes/collections.py")
    worker = backend("app/worker.py")
    webhooks = backend("app/api/routes/webhooks.py")

    assert "class TestCollectionMessageRequest" in communications_schema
    assert "class TestCollectionMessageResult" in communications_schema
    assert '"/collections/{collection_id}/test-message"' in communications_route
    assert 'kind="test"' in communications_route
    assert 'payment_reference="TEST"' in communications_route
    assert 'public_token="test-preview"' in communications_route
    assert 'CommunicationMessage.kind != "test"' in communications_route
    assert '"/{collection_id}/dispatch"' in collections_route
    assert 'CommunicationMessage.kind != "test"' in collections_route
    assert "queue_collection_messages(" in collections_route
    assert 'stored.kind == "initial"' in worker
    assert 'stored.kind == "reminder"' in worker
    assert 'outgoing.kind == "test"' in webhooks
    assert 'message.kind == "test"' in webhooks


def test_frontend_requires_confirmation_and_supports_test_delivery() -> None:
    collections = frontend("src/components/workspace/CollectionsPage.tsx")
    api = frontend("src/lib/api.ts")
    types = frontend("src/lib/types.ts")
    settings = frontend("src/components/workspace/SettingsPage.tsx")
    ux = frontend("src/locales/ux.ts")

    assert "SendConfirmationModal" in collections
    assert "confirmSend" in collections
    assert 'api.testCollectionMessage(item.id,"email")' in collections
    assert "previewCollectionDispatch:" in api
    assert "phone?: string | null" in types
    assert 't("phone")' in settings
    assert "confirmRealSend" in ux
    assert "sendTestMessage" in ux
