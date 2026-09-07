import re

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ContactRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=2, max_length=160)
    message: str = Field(min_length=20, max_length=4000)
    locale: str = Field(default="en", min_length=2, max_length=20)
    website: str = Field(default="", max_length=200)

    @field_validator("name", "subject")
    @classmethod
    def clean_single_line(cls, value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            raise ValueError("Value must not be empty")
        return cleaned

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message must not be empty")
        return cleaned

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        cleaned = value.strip().casefold()
        if not _EMAIL_RE.fullmatch(cleaned):
            raise ValueError("Invalid email address")
        return cleaned

    @field_validator("locale")
    @classmethod
    def clean_locale(cls, value: str) -> str:
        return value.strip() or "en"
