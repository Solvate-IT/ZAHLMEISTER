import re

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    locale: str = Field(default="en", max_length=20)
    currency: str = Field(default="EUR", min_length=3, max_length=3)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_RE.match(value):
            raise ValueError("Invalid email address")
        return value

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split()).strip()
        return value or None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_RE.match(value):
            raise ValueError("Invalid email address")
        return value


class UserRead(BaseModel):
    id: str
    email: str
    display_name: str
    organization_id: str
    organization_name: str
    locale: str
    currency: str
    email_verified: bool = False


class AuthResponse(BaseModel):
    token: str
    user: UserRead
