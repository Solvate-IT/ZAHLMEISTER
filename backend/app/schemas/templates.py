from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.templates import SUPPORTED_LANGUAGES, normalize_language, validate_template_body


def _validate_language(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_language(value, fallback="")
    if not normalized:
        raise ValueError(f"Unsupported language: {value}")
    return normalized


class MessageTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=10000)
    source_language: str | None = Field(default=None, max_length=10)

    @field_validator("source_language")
    @classmethod
    def validate_source_language(cls, value: str | None) -> str | None:
        return _validate_language(value)

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        body = value.strip()
        if not body:
            raise ValueError("Template text must not be empty")
        validate_template_body(body)
        return body


class MessageTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    translations: dict[str, str] | None = None
    is_default: bool | None = None

    @field_validator("translations")
    @classmethod
    def validate_translations(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        for language, body in value.items():
            normalized = _validate_language(language)
            if normalized not in SUPPORTED_LANGUAGES:
                raise ValueError(f"Unsupported language: {language}")
            if not body.strip():
                raise ValueError("Template text must not be empty")
            validate_template_body(body)
        return value


class MessageTemplateTranslateRequest(BaseModel):
    source_language: str = Field(max_length=10)

    @field_validator("source_language")
    @classmethod
    def validate_source_language(cls, value: str) -> str:
        normalized = _validate_language(value)
        assert normalized is not None
        return normalized


class MessageTemplateTranslationStatus(BaseModel):
    configured: bool
    provider: str = "google_cloud_translation"
    supported_languages: list[str] = Field(default_factory=list)


class MessageTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    translations: dict[str, str]
    is_default: bool


class TemplateVariableRead(BaseModel):
    key: str
