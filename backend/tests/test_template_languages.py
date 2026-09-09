import pytest

from app.services.participant_preferences import normalize_participant_locale
from app.services.templates import template_body_for_locale, validate_same_template_variables


def test_template_language_fallback_prefers_participant_then_organization_then_english() -> None:
    translations = {
        "fr": "Bonjour {{name}}",
        "de": "Hallo {{name}}",
        "en": "Hello {{name}}",
    }

    assert template_body_for_locale(translations, "fr-FR", fallback_locale="de-AT") == translations["fr"]
    assert template_body_for_locale(translations, "sl-SI", fallback_locale="de-AT") == translations["de"]
    assert template_body_for_locale(translations, "sl-SI", fallback_locale="it-IT") == translations["en"]


def test_participant_locale_is_optional_and_normalized() -> None:
    assert normalize_participant_locale(None) is None
    assert normalize_participant_locale("") is None
    assert normalize_participant_locale("de-AT") == "de"
    assert normalize_participant_locale("FR_fr") == "fr"
    with pytest.raises(ValueError, match="Unsupported language"):
        normalize_participant_locale("tr")


def test_translated_template_must_keep_exact_variables() -> None:
    validate_same_template_variables(
        "Hello {{contact}}, pay {{amount}}.",
        "Hallo {{contact}}, bitte {{amount}} bezahlen.",
    )
    with pytest.raises(ValueError, match="variables do not match"):
        validate_same_template_variables(
            "Hello {{contact}}, pay {{amount}}.",
            "Hallo {{contact}}.",
        )
