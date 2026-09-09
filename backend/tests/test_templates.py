import pytest

from app.services.templates import (
    SUPPORTED_LANGUAGES,
    default_template_body,
    default_template_translations,
    legacy_default_template_body,
    message_values,
    normalize_translations,
    render_template,
    validate_template_body,
)


def test_default_template_exists_for_all_eu_official_languages() -> None:
    translations = default_template_translations()
    assert set(translations) == set(SUPPORTED_LANGUAGES)
    assert len(translations) == 24
    for text in translations.values():
        assert "{{payment_link}}" in text
        assert "{{payment_reference}}" in text
        assert text.endswith("{{name}}")


def test_german_default_template_uses_requested_signoff() -> None:
    assert default_template_body("de").endswith("Mit freundlichen Grüßen\n{{name}}")


def test_legacy_default_template_is_upgraded_without_touching_custom_text() -> None:
    upgraded = normalize_translations({"de": legacy_default_template_body("de")})
    assert upgraded["de"] == default_template_body("de")
    custom = normalize_translations({"de": "Eigener Text {{name}}"})
    assert custom["de"] == "Eigener Text {{name}}"


def test_template_variables_render_without_touching_unknown_text() -> None:
    values = message_values(
        participant_name="Anna Muster",
        collection_name="Ausflug",
        amount="12.00",
        currency="EUR",
        payment_url="https://example.test/pay/abc",
        payment_reference="ZM-ABC",
        due_at=None,
    )
    rendered = render_template(
        "Hallo {{first_name}}, {{amount}} / {{collection_name}} / {{payment_reference}}",
        values,
    )
    assert rendered == "Hallo Anna, 12.00 EUR / Ausflug / ZM-ABC"


def test_unknown_template_variable_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown template variables"):
        validate_template_body("Hello {{unknown_value}}")
