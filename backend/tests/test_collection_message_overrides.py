from types import SimpleNamespace

import pytest

from app.schemas.workflow import CollectionCreate
from app.services import translation
from app.services.collection_message_overrides import (
    deserialize_collection_message_overrides,
    serialize_collection_message_overrides,
)
from app.services.message_renderer import render_collection_message


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


def test_collection_create_accepts_localized_overrides() -> None:
    payload = CollectionCreate(
        participant_list_id="00000000-0000-0000-0000-000000000001",
        amount="12.00",
        message_body_overrides={
            "de-AT": "Hallo {{contact}}",
            "fr": "Bonjour {{contact}}",
        },
    )
    assert payload.message_body_overrides == {
        "de": "Hallo {{contact}}",
        "fr": "Bonjour {{contact}}",
    }


@pytest.mark.asyncio
async def test_localized_override_uses_participant_language() -> None:
    collection = SimpleNamespace(
        message_body_override=serialize_collection_message_overrides(
            {"de": "Hallo {{contact}}", "fr": "Bonjour {{contact}}"}
        ),
        message_template_id=None,
        message_include_payment_link=False,
        message_include_payment_qr=False,
        name="Ausflug",
        amount="12.00",
        currency="EUR",
        due_at=None,
    )
    organization = SimpleNamespace(
        id="org",
        name="Schule",
        locale="de",
        message_include_payment_link=False,
        message_include_payment_qr=False,
        bank_account_name=None,
        bank_iban=None,
        bank_bic=None,
    )
    participant = SimpleNamespace(id="participant", name="Jean Dupont")
    collection_participant = SimpleNamespace(public_token="token", payment_reference="ZM-1")

    rendered = await render_collection_message(
        None,
        collection=collection,
        collection_participant=collection_participant,
        participant=participant,
        organization=organization,
        participant_locale="fr",
    )
    assert rendered.text == "Bonjour Jean Dupont"


@pytest.mark.asyncio
async def test_localized_override_rejects_missing_participant_language() -> None:
    collection = SimpleNamespace(
        message_body_override=serialize_collection_message_overrides(
            {"de": "Hallo {{contact}}"}
        ),
        message_template_id=None,
        message_include_payment_link=False,
        message_include_payment_qr=False,
        name="Ausflug",
        amount="12.00",
        currency="EUR",
        due_at=None,
    )
    organization = SimpleNamespace(
        id="org",
        name="Schule",
        locale="de",
        message_include_payment_link=False,
        message_include_payment_qr=False,
        bank_account_name=None,
        bank_iban=None,
        bank_bic=None,
    )
    participant = SimpleNamespace(id="participant", name="Jean Dupont")
    collection_participant = SimpleNamespace(public_token="token", payment_reference="ZM-1")

    with pytest.raises(ValueError, match="Missing collection message translation for language: fr"):
        await render_collection_message(
            None,
            collection=collection,
            collection_participant=collection_participant,
            participant=participant,
            organization=organization,
            participant_locale="fr",
        )


@pytest.mark.asyncio
async def test_translate_other_languages_replaces_requested_targets(monkeypatch) -> None:
    async def fake_translate_text(body: str, *, target_language: str, source_language: str | None = None) -> str:
        assert body == "Hallo {{contact}}"
        assert source_language == "de"
        return f"{target_language}: {{{{contact}}}}"

    monkeypatch.setattr(translation, "translate_text", fake_translate_text)
    result = await translation.translate_other_languages(
        "Hallo {{contact}}",
        source_language="de",
        target_languages=["de", "fr", "it"],
    )
    assert result == {
        "de": "Hallo {{contact}}",
        "fr": "fr: {{contact}}",
        "it": "it: {{contact}}",
    }
