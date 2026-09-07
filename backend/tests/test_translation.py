import pytest

from app.services import translation


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_translation_preserves_template_variables(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    class Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> bool:
            return False

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return _Response(
                {"data": {"translations": [{"translatedText": "Hallo __ZMVAR_0__"}]}}
            )

    monkeypatch.setattr(translation.settings, "google_translate_api_key", "test-key")
    monkeypatch.setattr(
        translation.settings,
        "google_translate_api_url",
        "https://translation.googleapis.com/language/translate/v2",
    )
    monkeypatch.setattr(translation.httpx, "AsyncClient", Client)

    result = await translation.translate_text(
        "Hello {{first_name}}",
        target_language="de",
        source_language="en",
    )

    assert result == "Hallo {{first_name}}"
    assert calls[0][1]["json"]["q"] == "Hello __ZMVAR_0__"
    assert calls[0][1]["json"]["source"] == "en"


@pytest.mark.asyncio
async def test_translate_missing_never_overwrites_existing_languages(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_translate_text(
        body: str,
        *,
        target_language: str,
        source_language: str | None = None,
    ) -> str:
        calls.append(target_language)
        return f"Translated {target_language} {{{{name}}}}"

    monkeypatch.setattr(translation, "SUPPORTED_LANGUAGES", ("de", "en", "fr"))
    monkeypatch.setattr(translation, "translate_text", fake_translate_text)

    source = "Hallo {{name}}"
    result = await translation.translate_missing(
        source,
        source_language="de",
        existing={"de": source, "fr": "Manuel {{name}}"},
    )

    assert calls == ["en"]
    assert result["de"] == source
    assert result["fr"] == "Manuel {{name}}"
    assert result["en"] == "Translated en {{name}}"


@pytest.mark.asyncio
async def test_language_detection_returns_supported_language(monkeypatch) -> None:
    class Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> bool:
            return False

        async def post(self, url, **kwargs):
            assert url.endswith("/language/translate/v2/detect")
            assert "{{first_name}}" not in kwargs["json"]["q"]
            return _Response(
                {"data": {"detections": [[{"language": "fr", "confidence": 0.99}]]}}
            )

    monkeypatch.setattr(translation.settings, "google_translate_api_key", "test-key")
    monkeypatch.setattr(
        translation.settings,
        "google_translate_api_url",
        "https://translation.googleapis.com/language/translate/v2",
    )
    monkeypatch.setattr(translation.httpx, "AsyncClient", Client)

    assert await translation.detect_language("Bonjour {{first_name}}") == "fr"
