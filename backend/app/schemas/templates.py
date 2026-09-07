from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.templates import SUPPORTED_LANGUAGES, validate_template_body


class MessageTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


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
            normalized = language.split("-", 1)[0].lower()
            if normalized not in SUPPORTED_LANGUAGES:
                raise ValueError(f"Unsupported language: {language}")
            if not body.strip():
                raise ValueError("Template text must not be empty")
            validate_template_body(body)
        return value


class MessageTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    translations: dict[str, str]
    is_default: bool


class TemplateVariableRead(BaseModel):
    key: str
