import pytest

from app.services import translation
from app.services.collection_message_overrides import (
    deserialize_collection_message_overrides,
    serialize_collection_message_overrides,
)


def test_legacy_collection_override_remains_readable() -> None:
    translations, legacy = deserialize_collection_message_overrides(
        "Hallo {{contact}}",
        fallback_language="de",
    )
    assert legacy is True
    assert translations == {"de": "Hallo {{contact}}"}


def test_localized_collection_overrides_roundtrip() -> None:
    stored = serialize_collection_message_overrides(
        {"de": "Hallo {{contact}}", "fr": "Bonjour {{contact}}"}
    )
    translations, legacy = deserialize_collection_message_overrides(
        stored,
        fallback_language="de",
    )
    assert legacy is False
    assert translations == {
        "de": "Hallo {{contact}}",
        "fr": "Bonjour {{contact}}",
    }


@pytest.mark.asyncio
async def test_translate_other_languages_replaces_requested_targets(monkeypatch) -> None:
    async def fake_translate_text(body: str, *, target_language: str, source_language: str | None = None) -> str:
        assert body == "Hallo {{contact}}"
        assert source_language == "de"
        return f"{target_language}: {{contact}}"

    monkeypatch.setattr(translation, "translate_text", fake_translate_text)
    result = await translation.translate_other_languages(
        "Hallo {{contact}}",
        source_language="de",
        target_languages=["de", "fr", "it"],
    )
    assert result == {
        "de": "Hallo {{contact}}",
        "fr": "fr: {contact}",
        "it": "it: {contact}",
    }
