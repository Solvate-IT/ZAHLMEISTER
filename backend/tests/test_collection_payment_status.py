from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.collections import _require_manual_payment_change


class PaymentSession:
    def __init__(self, method: str | None):
        self.method = method

    async def scalar(self, statement):
        query = str(statement)
        assert "payments.method !=" in query
        return self.method if self.method != "manual" else None


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["online", "bank_import", "bank_sync"])
async def test_external_payments_cannot_be_changed_manually(method: str) -> None:
    with pytest.raises(HTTPException) as error:
        await _require_manual_payment_change(PaymentSession(method), uuid4())
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("method", [None, "manual"])
async def test_manual_payments_can_be_changed(method: str | None) -> None:
    await _require_manual_payment_change(PaymentSession(method), uuid4())
