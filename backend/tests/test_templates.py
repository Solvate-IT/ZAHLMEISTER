import pytest

from app.services.templates import (
    SUPPORTED_LANGUAGES,
    default_template_body,
    default_template_translations,
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
        assert "{{contact}}" in text
        assert "{{payment_link}}" in text
        assert "{{payment_reference}}" in text
        assert "{{first_name}}" not in text
        assert text.endswith("{{name}}")


def test_german_default_template_uses_requested_signoff() -> None:
    assert default_template_body("de").endswith("Mit freundlichen Grüßen\n{{name}}")


def test_translation_normalization_only_normalizes_language_keys_and_whitespace() -> None:
    assert normalize_translations({"de-AT": "  Eigener Text {{name}}  "}) == {
        "de": "Eigener Text {{name}}"
    }


def test_template_variables_render_with_account_contact_and_organisation() -> None:
    values = message_values(
        sender_name="Max Mustermann",
        participant_name="Anna Muster",
        organization_name="Schulverein Muster",
        collection_name="Ausflug",
        amount="12.00",
        currency="EUR",
        payment_url="https://example.test/pay/abc",
        payment_reference="ZM-ABC",
        due_at=None,
    )
    rendered = render_template(
        "Hallo {{contact}}, {{amount}} / {{collection_name}} / {{organisation}} / {{name}}",
        values,
    )
    assert rendered == "Hallo Anna Muster, 12.00 EUR / Ausflug / Schulverein Muster / Max Mustermann"


def test_first_name_is_not_a_valid_template_variable() -> None:
    with pytest.raises(ValueError, match="Unknown template variables"):
        validate_template_body("Hallo {{first_name}}")


def test_render_rejects_obsolete_template_variables() -> None:
    with pytest.raises(ValueError, match="Unknown template variables"):
        render_template("Hallo {{first_name}}", {"contact": "Anna Muster"})


def test_unknown_template_variable_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown template variables"):
        validate_template_body("Hello {{unknown_value}}")
