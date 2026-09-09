import json

from app.services.templates import normalize_translations


def deserialize_collection_message_overrides(value: str | None) -> dict[str, str]:
    if not value or not value.strip():
        return {}

    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid localized collection message data") from exc
    if not isinstance(raw, dict):
        raise ValueError("Invalid localized collection message data")
    return normalize_translations(raw)


def serialize_collection_message_overrides(translations: dict[str, str]) -> str | None:
    normalized = normalize_translations(translations)
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)
