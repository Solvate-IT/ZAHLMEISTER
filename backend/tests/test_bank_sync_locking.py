"""Bank sync never calls the bank while a database transaction is open.

Holding the connection's row lock across the Ponto calls made the token refresh
(its own transaction on the same row) wait on itself — a deadlock PostgreSQL
cannot detect, which stopped the worker for every tenant.
"""
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.entities import BankSyncConnection
from app.services import bank_sync


@pytest.mark.asyncio
async def test_provider_is_only_called_with_no_transaction_open(monkeypatch) -> None:
    open_transactions = 0
    connection = BankSyncConnection(organization_id=uuid4(), provider="ponto", status="connected")
    connection.id = uuid4()

    class Session:
        async def get(self, model, key, with_for_update=False):
            return connection

        async def execute(self, statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

        async def scalar(self, statement):
            return uuid4()  # an open participant exists, so transactions are fetched

        def expunge(self, instance):
            pass

    class Context:
        async def __aenter__(self):
            nonlocal open_transactions
            open_transactions += 1
            return Session()

        async def __aexit__(self, *exc):
            nonlocal open_transactions
            open_transactions -= 1
            return False

    class Factory:
        def __call__(self):
            return Context()

        def begin(self):
            return Context()

    monkeypatch.setattr(bank_sync, "SessionLocal", Factory())

    calls = []

    class Provider:
        async def list_accounts(self, conn):
            assert open_transactions == 0, "provider called inside a transaction"
            calls.append("accounts")
            return [{"id": "acc-1", "attributes": {"currency": "EUR"}}]

        async def list_transactions(self, conn, account_id):
            assert open_transactions == 0, "provider called inside a transaction"
            calls.append(f"transactions:{account_id}")
            return []

    applied = []

    async def apply(session, stored, remote_accounts, remote_transactions):
        assert open_transactions == 1
        applied.append((remote_accounts, remote_transactions))
        return {"imported": 0, "auto_matched": 0, "needs_review": 0, "duplicates": 0, "synced_at": datetime.now(UTC)}

    monkeypatch.setattr(bank_sync, "get_bank_sync_provider", lambda name: Provider())
    monkeypatch.setattr(bank_sync, "_apply_sync", apply)
    result = await bank_sync.sync_connection(connection.id)
    assert calls == ["accounts", "transactions:acc-1"]
    assert applied and applied[0][1] == {"acc-1": []}
    assert result["imported"] == 0
