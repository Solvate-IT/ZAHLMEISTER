import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.app_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_config(data: dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _fernet().encrypt(raw).decode("ascii")


def decrypt_config(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        raw = _fernet().decrypt(value.encode("ascii"))
        loaded = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Stored credentials cannot be decrypted") from exc
    return loaded if isinstance(loaded, dict) else {}
