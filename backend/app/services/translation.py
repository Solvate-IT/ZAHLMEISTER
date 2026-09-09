import asyncio
import html
import re

import httpx

from app.core.config import settings
from app.services.templates import (
    SUPPORTED_LANGUAGES,
    normalize_language,
    validate_same_template_variables,
    validate_template_body,
)

_TOKEN_RE = re.compile(r"{{\s*[a-z_]+\s*}}")


def configured() -> bool:
    return bool(settings.google_translate_api_key.strip())


def _protect_variables(body: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        marker = f"__ZMVAR_{len(replacements)}__"
        replacements[marker] = match.group(0)
        return marker

    return _TOKEN_RE.sub(replace, body), replacements


def _restore_variables(body: str, replacements: dict[str, str]) -> str:
    result = html.unescape(body)
    for marker, original in replacements.items():
        if marker not in result:
            raise ValueError("Translation provider changed a protected template variable")
        result = result.replace(marker, original)
    return result


async def detect_language(body: str) -> str:
    validate_template_body(body)
    if not configured():
        raise ValueError("Automatic translation is not configured")
    text = _TOKEN_RE.sub(" ", body).strip()
    if not text:
        raise ValueError("Template has no text that can be used for language detection")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                settings.google_translate_api_url.rstrip("/") + "/detect",
                params={"key": settings.google_translate_api_key},
                json={"q": text},
            )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Automatic language detection failed") from exc
    detections = data.get("data", {}).get("detections", [])
    first_group = detections[0] if detections and isinstance(detections[0], list) else []
    first = first_group[0] if first_group and isinstance(first_group[0], dict) else {}
    detected = str(first.get("language") or "").split("-", 1)[0].lower()
    if detected not in SUPPORTED_LANGUAGES:
        raise ValueError("Detected source language is not supported by Zahlmeister")
    return detected


async def translate_text(
    body: str,
    *,
    target_language: str,
    source_language: str | None = None,
) -> str:
    validate_template_body(body)
    if not configured():
        raise ValueError("Automatic translation is not configured")
    target = normalize_language(target_language)
    source = normalize_language(source_language) if source_language else None
    protected, replacements = _protect_variables(body)
    payload: dict[str, str] = {
        "q": protected,
        "target": target,
        "format": "text",
    }
    if source:
        payload["source"] = source
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                settings.google_translate_api_url,
                params={"key": settings.google_translate_api_key},
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Automatic translation provider request failed") from exc
    rows = data.get("data", {}).get("translations", [])
    if not rows or not isinstance(rows[0], dict):
        raise RuntimeError("Automatic translation provider returned no translation")
    translated = _restore_variables(str(rows[0].get("translatedText") or ""), replacements).strip()
    if not translated:
        raise RuntimeError("Automatic translation provider returned an empty translation")
    validate_same_template_variables(body, translated)
    return translated


async def _translate_languages(
    source_text: str,
    *,
    source_language: str | None,
    target_languages: list[str],
) -> dict[str, str]:
    validate_template_body(source_text)
    source = normalize_language(source_language) if source_language else None
    targets = [
        normalize_language(language)
        for language in dict.fromkeys(target_languages)
        if normalize_language(language) != source
    ]
    if not targets:
        return {}

    semaphore = asyncio.Semaphore(4)

    async def translate_one(language: str) -> tuple[str, str]:
        async with semaphore:
            translated = await translate_text(
                source_text,
                target_language=language,
                source_language=source,
            )
            return language, translated

    return dict(await asyncio.gather(*(translate_one(language) for language in targets)))


async def translate_missing(
    source_text: str,
    *,
    source_language: str | None,
    existing: dict[str, str],
) -> dict[str, str]:
    result = dict(existing)
    missing = [language for language in SUPPORTED_LANGUAGES if language not in result]
    result.update(
        await _translate_languages(
            source_text,
            source_language=source_language,
            target_languages=missing,
        )
    )
    return result


async def translate_other_languages(
    source_text: str,
    *,
    source_language: str,
    target_languages: list[str] | None = None,
) -> dict[str, str]:
    source = normalize_language(source_language)
    targets = target_languages or list(SUPPORTED_LANGUAGES)
    translated = await _translate_languages(
        source_text,
        source_language=source,
        target_languages=targets,
    )
    return {source: source_text, **translated}
