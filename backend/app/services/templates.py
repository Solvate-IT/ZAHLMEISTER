import gettext
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

SUPPORTED_LANGUAGES = (
    "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu",
    "ga", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv",
)

DEFAULT_TEMPLATE_NAME_MSGID = "Payment request"
DEFAULT_TEMPLATE_BODY_MSGID = (
    "Hello {{first_name}},\n\n"
    "Please pay {{amount}} for {{collection_name}}.\n\n"
    "Pay here: {{payment_link}}\n"
    "Payment reference: {{payment_reference}}"
)

TEMPLATE_VARIABLES = (
    "first_name",
    "name",
    "collection_name",
    "amount",
    "due_date",
    "payment_link",
    "payment_reference",
)

_LOCALE_DIR = Path(__file__).resolve().parents[2] / "locales"
_TOKEN_RE = re.compile(r"{{\s*([a-z_]+)\s*}}")


def _translation(language: str) -> gettext.NullTranslations:
    return gettext.translation(
        "messages",
        localedir=_LOCALE_DIR,
        languages=[language],
        fallback=True,
    )


def default_template_name(language: str = "en") -> str:
    language = language.split("-", 1)[0].lower()
    return _translation(language).gettext(DEFAULT_TEMPLATE_NAME_MSGID)


def default_template_body(language: str = "en") -> str:
    language = language.split("-", 1)[0].lower()
    return _translation(language).gettext(DEFAULT_TEMPLATE_BODY_MSGID)


def default_template_translations() -> dict[str, str]:
    return {language: default_template_body(language) for language in SUPPORTED_LANGUAGES}


def normalize_translations(value: str | dict[str, str]) -> dict[str, str]:
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except json.JSONDecodeError:
            raw = {}
    else:
        raw = value
    result: dict[str, str] = {}
    for key, text in raw.items():
        language = str(key).split("-", 1)[0].lower()
        if language in SUPPORTED_LANGUAGES and isinstance(text, str) and text.strip():
            result[language] = text.strip()
    return result


def serialize_translations(translations: dict[str, str]) -> str:
    return json.dumps(translations, ensure_ascii=False, sort_keys=True)


def template_body_for_locale(translations: dict[str, str], locale: str) -> str:
    language = locale.split("-", 1)[0].lower()
    return (
        translations.get(language)
        or translations.get("en")
        or default_template_body(language)
    )


def validate_template_body(body: str) -> None:
    unknown = sorted(set(_TOKEN_RE.findall(body)) - set(TEMPLATE_VARIABLES))
    if unknown:
        raise ValueError(f"Unknown template variables: {', '.join(unknown)}")


def render_template(body: str, values: dict[str, Any]) -> str:
    validate_template_body(body)

    def replace(match: re.Match[str]) -> str:
        value = values.get(match.group(1), "")
        return "" if value is None else str(value)

    return _TOKEN_RE.sub(replace, body)


def message_values(
    *,
    participant_name: str,
    collection_name: str,
    amount: Decimal | str,
    currency: str,
    payment_url: str,
    payment_reference: str,
    due_at: datetime | None,
) -> dict[str, str]:
    name = " ".join(participant_name.split()).strip()
    first_name = name.split(" ", 1)[0] if name else ""
    amount_text = f"{Decimal(amount):.2f} {currency}" if not isinstance(amount, str) else f"{amount} {currency}"
    return {
        "first_name": first_name,
        "name": name,
        "collection_name": collection_name,
        "amount": amount_text,
        "due_date": due_at.date().isoformat() if due_at else "",
        "payment_link": payment_url,
        "payment_reference": payment_reference,
    }
