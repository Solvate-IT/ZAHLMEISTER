import gettext
import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

SUPPORTED_LANGUAGES = (
    "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu",
    "ga", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv",
)

DEFAULT_TEMPLATE_NAME_MSGID = "Payment request"
# Keep the historical gettext msgid so existing compiled translations remain usable.
# The obsolete first_name token is converted to contact after translation.
DEFAULT_TEMPLATE_BODY_MSGID = (
    "Hello {{first_name}},\n\n"
    "Please pay {{amount}} for {{collection_name}}.\n\n"
    "Pay here: {{payment_link}}\n"
    "Payment reference: {{payment_reference}}"
)
DEFAULT_TEMPLATE_SIGNOFFS = {
    "bg": "С уважение",
    "hr": "Srdačan pozdrav",
    "cs": "S pozdravem",
    "da": "Med venlig hilsen",
    "nl": "Met vriendelijke groet",
    "en": "Kind regards",
    "et": "Lugupidamisega",
    "fi": "Ystävällisin terveisin",
    "fr": "Cordialement",
    "de": "Mit freundlichen Grüßen",
    "el": "Με εκτίμηση",
    "hu": "Üdvözlettel",
    "ga": "Le dea-mhéin",
    "it": "Cordiali saluti",
    "lv": "Ar cieņu",
    "lt": "Pagarbiai",
    "mt": "Tislijiet",
    "pl": "Z poważaniem",
    "pt": "Com os melhores cumprimentos",
    "ro": "Cu stimă",
    "sk": "S pozdravom",
    "sl": "Lep pozdrav",
    "es": "Atentamente",
    "sv": "Med vänliga hälsningar",
}

TEMPLATE_VARIABLES = (
    "name",
    "contact",
    "collection_name",
    "amount",
    "due_date",
    "payment_link",
    "payment_reference",
)

_LOCALE_DIR = Path(__file__).resolve().parents[2] / "locales"
_TOKEN_RE = re.compile(r"{{\s*([a-z_]+)\s*}}")
_LEGACY_FIRST_NAME_RE = re.compile(r"{{\s*first_name\s*}}")


def normalize_language(value: str | None, *, fallback: str = "en") -> str:
    language = (value or fallback).strip().lower().split("-", 1)[0].split("_", 1)[0]
    return language if language in SUPPORTED_LANGUAGES else fallback


def _translation(language: str) -> gettext.NullTranslations:
    return gettext.translation(
        "messages",
        localedir=_LOCALE_DIR,
        languages=[language],
        fallback=True,
    )


def default_template_name(language: str = "en") -> str:
    return _translation(normalize_language(language)).gettext(DEFAULT_TEMPLATE_NAME_MSGID)


def legacy_default_template_body(language: str = "en") -> str:
    normalized = normalize_language(language)
    return _translation(normalized).gettext(DEFAULT_TEMPLATE_BODY_MSGID)


def _replace_legacy_first_name(body: str) -> str:
    return _LEGACY_FIRST_NAME_RE.sub("{{contact}}", body)


def previous_default_template_body(language: str = "en") -> str:
    normalized = normalize_language(language)
    return (
        f"{legacy_default_template_body(normalized)}\n\n"
        f"{DEFAULT_TEMPLATE_SIGNOFFS.get(normalized, DEFAULT_TEMPLATE_SIGNOFFS['en'])}\n"
        "{{name}}"
    )


def default_template_body(language: str = "en") -> str:
    normalized = normalize_language(language)
    translated_body = _replace_legacy_first_name(legacy_default_template_body(normalized))
    return (
        f"{translated_body}\n\n"
        f"{DEFAULT_TEMPLATE_SIGNOFFS.get(normalized, DEFAULT_TEMPLATE_SIGNOFFS['en'])}\n"
        "{{name}}"
    )


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
            normalized_text = text.strip()
            if normalized_text in {
                legacy_default_template_body(language).strip(),
                previous_default_template_body(language).strip(),
            }:
                normalized_text = default_template_body(language)
            else:
                normalized_text = _replace_legacy_first_name(normalized_text)
            result[language] = normalized_text
    return result


def serialize_translations(translations: dict[str, str]) -> str:
    return json.dumps(translations, ensure_ascii=False, sort_keys=True)


def template_body_for_locale(
    translations: dict[str, str],
    locale: str,
    *,
    fallback_locale: str | None = None,
) -> str:
    language = normalize_language(locale)
    fallback_language = normalize_language(fallback_locale) if fallback_locale else None
    return (
        translations.get(language)
        or (translations.get(fallback_language) if fallback_language else None)
        or translations.get("en")
        or default_template_body(language)
    )


def template_variable_counts(body: str) -> Counter[str]:
    return Counter(_TOKEN_RE.findall(body))


def validate_template_body(body: str) -> None:
    unknown = sorted(set(_TOKEN_RE.findall(body)) - set(TEMPLATE_VARIABLES))
    if unknown:
        raise ValueError(f"Unknown template variables: {', '.join(unknown)}")


def validate_same_template_variables(source: str, translated: str) -> None:
    validate_template_body(translated)
    if template_variable_counts(source) != template_variable_counts(translated):
        raise ValueError("Translated template variables do not match the source template")


def render_template(body: str, values: dict[str, Any]) -> str:
    # Stored collection overrides may predate the removal of first_name. They render
    # as the full contact name but new/edited templates no longer accept that token.
    body = _replace_legacy_first_name(body)
    validate_template_body(body)

    def replace(match: re.Match[str]) -> str:
        value = values.get(match.group(1), "")
        return "" if value is None else str(value)

    return _TOKEN_RE.sub(replace, body)


def message_values(
    *,
    sender_name: str,
    participant_name: str,
    collection_name: str,
    amount: Decimal | str,
    currency: str,
    payment_url: str,
    payment_reference: str,
    due_at: datetime | None,
) -> dict[str, str]:
    sender = " ".join(sender_name.split()).strip()
    contact = " ".join(participant_name.split()).strip()
    amount_text = (
        f"{Decimal(amount):.2f} {currency}"
        if not isinstance(amount, str)
        else f"{amount} {currency}"
    )
    return {
        "name": sender,
        "contact": contact,
        "collection_name": collection_name,
        "amount": amount_text,
        "due_date": due_at.date().isoformat() if due_at else "",
        "payment_link": payment_url,
        "payment_reference": payment_reference,
    }
