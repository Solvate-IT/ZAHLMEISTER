from pydantic import BaseModel, Field, field_validator

from app.schemas.passwords import PASSWORD_MIN_LENGTH, validate_password_strength


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=500)


class ResetPasswordRequest(TokenRequest):
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=200)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=200)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    organization_name: str | None = Field(default=None, max_length=200)
    locale: str | None = Field(default=None, max_length=20)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("display_name", "organization_name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("Name must not be empty")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)
