from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DigitalServiceTaxPolicy:
    version: str
    seller_country: str
    eu_oss_enabled: bool
    eu_standard_rates: dict[str, Decimal]


DIGITAL_SERVICE_TAX_POLICY = DigitalServiceTaxPolicy(
    version="2026-09-08",
    seller_country="AT",
    eu_oss_enabled=True,
    eu_standard_rates={
        "AT": Decimal("20.0"),
        "BE": Decimal("21.0"),
        "BG": Decimal("20.0"),
        "HR": Decimal("25.0"),
        "CY": Decimal("19.0"),
        "CZ": Decimal("21.0"),
        "DK": Decimal("25.0"),
        "EE": Decimal("24.0"),
        "FI": Decimal("25.5"),
        "FR": Decimal("20.0"),
        "DE": Decimal("19.0"),
        "GR": Decimal("24.0"),
        "HU": Decimal("27.0"),
        "IE": Decimal("23.0"),
        "IT": Decimal("22.0"),
        "LV": Decimal("21.0"),
        "LT": Decimal("21.0"),
        "LU": Decimal("17.0"),
        "MT": Decimal("18.0"),
        "NL": Decimal("21.0"),
        "PL": Decimal("23.0"),
        "PT": Decimal("23.0"),
        "RO": Decimal("21.0"),
        "SK": Decimal("23.0"),
        "SI": Decimal("22.0"),
        "ES": Decimal("21.0"),
        "SE": Decimal("25.0"),
    },
)
