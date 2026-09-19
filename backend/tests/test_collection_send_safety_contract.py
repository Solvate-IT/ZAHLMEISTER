from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT.parent / "frontend"


def backend(path: str) -> str:
    return (ROOT / path).read_text()


def frontend(path: str) -> str:
    return (FRONTEND / path).read_text()


def test_account_phone_is_persisted_and_exposed_for_test_delivery() -> None:
    entities = backend("app/models/entities.py")
    account_schema = backend("app/schemas/account.py")
    auth_schema = backend("app/schemas/auth.py")
    account_route = backend("app/api/routes/account.py")
    bootstrap = backend("app/db/bootstrap.py")

    assert "phone: Mapped[str | None]" in entities
    assert "phone: str | None" in account_schema
    assert "phone: str | None" in auth_schema
    assert "phone=user.phone" in account_route
    assert "stored.phone = payload.phone" in account_route
    assert "ADD COLUMN IF NOT EXISTS phone VARCHAR(50)" in bootstrap


def test_backend_has_non_mutating_test_delivery_and_real_dispatch_endpoint() -> None:
    communications_schema = backend("app/schemas/communications.py")
    communications_route = backend("app/api/routes/communications.py")
    collections_route = backend("app/api/routes/collections.py")
    worker = backend("app/worker.py")

    assert "class TestCollectionMessageRequest" in communications_schema
    assert "class TestCollectionMessageResult" in communications_schema
    assert '"/collections/{collection_id}/test-message"' in communications_route
    assert 'kind="test"' in communications_route
    assert "CommunicationMessage.kind != "test"" in communications_route
    assert '"/{collection_id}/dispatch"' in collections_route
    assert "queue_collection_messages(" in collections_route
    assert 'stored.kind == "initial"' in worker
    assert 'stored.kind == "reminder"' in worker


def test_frontend_requires_confirmation_and_supports_test_delivery() -> None:
    collections = frontend("src/components/workspace/CollectionsPage.tsx")
    api = frontend("src/lib/api.ts")
    types = frontend("src/lib/types.ts")
    settings = frontend("src/components/workspace/SettingsPage.tsx")
    ux = frontend("src/locales/ux.ts")

    assert "SendConfirmationModal" in collections
    assert "confirmSend" in collections
    assert "testCollectionMessage" in collections
    assert "testCollectionMessage:" in api
    assert "phone?: string | null" in types
    assert 't("phone")' in settings
    assert "confirmRealSend" in ux
    assert "sendTestMessage" in ux
