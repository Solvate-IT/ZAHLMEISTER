"""Store phone recipients in the international format required by messaging providers."""

import phonenumbers


def preferred_phone_region(locale: str | None, country: str | None = None) -> str:
    """Use the account country, then an explicit locale region, then Austria."""
    if country and country.upper() in phonenumbers.SUPPORTED_REGIONS:
        return country.upper()
    parts = (locale or "").replace("_", "-").split("-")
    if len(parts) > 1 and parts[1].upper() in phonenumbers.SUPPORTED_REGIONS:
        return parts[1].upper()
    return "AT"


def normalize_phone_number(value: str | None, region: str = "AT") -> str | None:
    """Reject ambiguous input instead of sending a local number to the wrong person."""
    if value is None or not value.strip():
        return None
    try:
        parsed = phonenumbers.parse(value.strip(), region)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Invalid phone number; include the country code if needed") from exc
    if parsed.extension or not phonenumbers.is_valid_number(parsed):
        raise ValueError("Invalid phone number; include the country code if needed")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
