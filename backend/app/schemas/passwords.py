import re

PASSWORD_MIN_LENGTH = 6
_LETTER_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-žΑ-ωА-я]")
_DIGIT_RE = re.compile(r"\d")


def validate_password_strength(value: str) -> str:
    if len(value) < PASSWORD_MIN_LENGTH or not _LETTER_RE.search(value) or not _DIGIT_RE.search(value):
        raise ValueError(
            "Password must be at least 6 characters long and contain at least one letter and one number"
        )
    return value
