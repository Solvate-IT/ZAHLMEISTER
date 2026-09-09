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
        "Hello {{contact}}",
        target_language="de",
        source_language="en",
    )

    assert result == "Hallo {{contact}}"
    assert calls[0][1]["json"]["q"] == "Hello __ZMVAR_0__"
    assert calls[0][1]["json"]["source"] == "en"
