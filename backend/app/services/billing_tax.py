from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from xml.etree import ElementTree

import httpx

from app.core.tax_catalog import DIGITAL_SERVICE_TAX_POLICY
from app.models.billing import BillingProfile

VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
_VAT_CLEAN_RE = re.compile(r"[^A-Z0-9]")


class BillingTaxError(RuntimeError):
    pass


class BillingTaxUnsupportedJurisdiction(BillingTaxError):
    pass


class BillingTaxValidationUnavailable(BillingTaxError):
    pass


class BillingTaxInvalidVatNumber(BillingTaxError):
    pass


@dataclass(frozen=True)
class TaxDecision:
    rate: Decimal
    vat_scheme: str
    treatment: str
    rule_version: str
    vat_validation_status: str
    vat_validated_at: datetime | None = None


def _normalized_vat_number(value: str) -> tuple[str, str]:
    cleaned = _VAT_CLEAN_RE.sub("", value.strip().upper())
    if len(cleaned) < 4 or not cleaned[:2].isalpha():
        raise BillingTaxInvalidVatNumber("VAT number must include its two-letter country prefix")
    country = cleaned[:2]
    number = cleaned[2:]
    if country == "GR":
        country = "EL"
    return country, number


async def validate_vies_vat_number(value: str) -> bool:
    country, number = _normalized_vat_number(value)
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">'
        '<soapenv:Header/><soapenv:Body><urn:checkVat>'
        f'<urn:countryCode>{country}</urn:countryCode><urn:vatNumber>{number}</urn:vatNumber>'
        '</urn:checkVat></soapenv:Body></soapenv:Envelope>'
    )
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(
                VIES_URL,
                content=body.encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise BillingTaxValidationUnavailable("EU VAT validation is temporarily unavailable") from exc
    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise BillingTaxValidationUnavailable("EU VAT validation returned an invalid response") from exc
    valid = next((item.text for item in root.iter() if item.tag.endswith("valid")), None)
    if valid is None:
        fault = next((item.text for item in root.iter() if item.tag.endswith("faultstring")), None)
        if fault:
            raise BillingTaxValidationUnavailable("EU VAT validation is temporarily unavailable")
        raise BillingTaxValidationUnavailable("EU VAT validation returned an incomplete response")
    return valid.strip().lower() == "true"


async def tax_decision(profile: BillingProfile) -> TaxDecision:
    policy = DIGITAL_SERVICE_TAX_POLICY
    country = profile.country.strip().upper()
    if country not in policy.eu_standard_rates:
        raise BillingTaxUnsupportedJurisdiction(
            "Automatic tax calculation is not yet configured for this billing country"
        )

    if country == policy.seller_country:
        return TaxDecision(
            rate=policy.eu_standard_rates[country],
            vat_scheme="standard",
            treatment="domestic_standard",
            rule_version=policy.version,
            vat_validation_status="not_required",
        )

    if profile.customer_type == "business":
        if not profile.vat_number:
            raise BillingTaxInvalidVatNumber("An EU business customer requires a VAT number")
        vat_country, _ = _normalized_vat_number(profile.vat_number)
        expected_country = "EL" if country == "GR" else country
        if vat_country != expected_country:
            raise BillingTaxInvalidVatNumber("VAT number country does not match billing country")
        valid = await validate_vies_vat_number(profile.vat_number)
        if not valid:
            raise BillingTaxInvalidVatNumber("VAT number could not be validated in VIES")
        now = datetime.now(UTC)
        return TaxDecision(
            rate=Decimal("0.0"),
            vat_scheme="standard",
            treatment="eu_reverse_charge",
            rule_version=policy.version,
            vat_validation_status="valid",
            vat_validated_at=now,
        )

    if not policy.eu_oss_enabled:
        raise BillingTaxUnsupportedJurisdiction("EU consumer billing requires an enabled OSS policy")
    return TaxDecision(
        rate=policy.eu_standard_rates[country],
        vat_scheme="one-stop-shop",
        treatment="eu_oss_consumer",
        rule_version=policy.version,
        vat_validation_status="not_required",
    )
