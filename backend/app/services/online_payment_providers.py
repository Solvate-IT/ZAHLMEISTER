from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import OnlinePaymentConnection


@dataclass(slots=True)
class OnlineCheckout:
    external_id: str
    checkout_url: str
    status: str
    expires_at: datetime | None = None


@dataclass(slots=True)
class OnlinePaymentStatus:
    external_id: str
    status: str
    amount: Decimal
    currency: str
    method: str | None = None
    paid_at: datetime | None = None
    expires_at: datetime | None = None


class OnlinePaymentProvider(Protocol):
    name: str

    async def test_connection(
        self, session: AsyncSession, connection: OnlinePaymentConnection
    ) -> None: ...

    async def create_checkout(
        self,
        session: AsyncSession,
        connection: OnlinePaymentConnection,
        *,
        amount: Decimal,
        currency: str,
        description: str,
        redirect_url: str,
        webhook_url: str,
        metadata: dict[str, str],
        locale: str | None,
        idempotency_key: str,
    ) -> OnlineCheckout: ...

    async def get_payment(
        self,
        session: AsyncSession,
        connection: OnlinePaymentConnection,
        external_id: str,
    ) -> OnlinePaymentStatus: ...
