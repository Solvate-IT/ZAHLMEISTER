from app.services.naming import (
    default_collection_name,
    default_participant_list_name,
    next_available_name,
)


def test_next_available_name_uses_base_when_free() -> None:
    assert next_available_name("Sammelaktion", []) == "Sammelaktion"


def test_next_available_name_appends_next_number() -> None:
    existing = ["Sammelaktion", "Sammelaktion 2", "Sammelaktion 4"]
    assert next_available_name("Sammelaktion", existing) == "Sammelaktion 3"


def test_next_available_name_is_case_insensitive() -> None:
    assert next_available_name("Teilnehmer", ["teilnehmer"]) == "Teilnehmer 2"


def test_default_names_follow_locale() -> None:
    assert default_participant_list_name("de-AT") == "Kontakte"
    assert default_collection_name("de-AT") == "Sammelaktion"
    assert default_participant_list_name("sl-SI") == "Stiki"
    assert default_collection_name("es-ES") == "Recaudación"


def test_all_eu_official_languages_have_default_names() -> None:
    from app.services.naming import DEFAULT_NAMES

    assert set(DEFAULT_NAMES) == {
        "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu",
        "ga", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv",
    }
