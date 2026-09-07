import re

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ImportParticipant(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("Name must not be empty")
        return value

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not value:
            return None
        if not _EMAIL_RE.match(value):
            raise ValueError("Invalid email address")
        return value

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split()).strip()
        return value or None


class ImportPreview(BaseModel):
    source_type: str
    participants: list[ImportParticipant]
    warnings: list[str] = Field(default_factory=list)


class ImportCommitRequest(BaseModel):
    participants: list[ImportParticipant] = Field(min_length=1, max_length=5000)


class ImportCommitResponse(BaseModel):
    imported_count: int
    skipped_count: int = 0
