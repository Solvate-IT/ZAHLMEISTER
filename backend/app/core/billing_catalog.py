from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BillingTariff:
    version: str
    product_id: str
    amount: Decimal
    currency: str
    interval: str


PRO_YEARLY_TARIFF = BillingTariff(
    version="2026-09-08",
    product_id="zahlmeister.pro.yearly",
    amount=Decimal("29.90"),
    currency="EUR",
    interval="12 months",
)
