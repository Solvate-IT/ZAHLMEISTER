from __future__ import annotations

from typing import Any, Protocol

from app.models.entities import BankSyncConnection
from app.services import ponto


class BankSyncProvider(Protocol):
    name: str

    async def list_accounts(self, connection: BankSyncConnection) -> list[dict[str, Any]]: ...

    async def list_transactions(
        self, connection: BankSyncConnection, account_external_id: str
    ) -> list[dict[str, Any]]: ...

    async def test_connection(self, connection: BankSyncConnection) -> None: ...


class PontoBankSyncProvider:
    name = "ponto"

    async def list_accounts(self, connection: BankSyncConnection) -> list[dict[str, Any]]:
        return await ponto.list_accounts(connection)

    async def list_transactions(
        self, connection: BankSyncConnection, account_external_id: str
    ) -> list[dict[str, Any]]:
        return await ponto.list_transactions(connection, account_external_id)

    async def test_connection(self, connection: BankSyncConnection) -> None:
        await ponto.test_connection(connection)


_PROVIDERS: dict[str, BankSyncProvider] = {
    "ponto": PontoBankSyncProvider(),
}


def get_bank_sync_provider(name: str) -> BankSyncProvider:
    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported BankSync provider: {name}") from exc
