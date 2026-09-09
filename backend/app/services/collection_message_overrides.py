import json

from app.services.templates import normalize_language, normalize_translations


def deserialize_collection_message_overrides(
    value: str | None,
    *,
    fallback_language: str,
) -> tuple[dict[str, str], bool]:
    """Return localized overrides and whether the stored value is a legacy plain-text override."""

    if not value or not value.strip():
        return {}, False

    stripped = value.strip()
    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError:
        return {normalize_language(fallback_language): stripped}, True

    if isinstance(raw, dict):
        return normalize_translations(raw), False

    return {normalize_language(fallback_language): stripped}, True


def serialize_collection_message_overrides(translations: dict[str, str]) -> str | None:
    normalized = normalize_translations(translations)
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)
