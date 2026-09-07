import json
import secrets
from datetime import UTC, datetime

from app.models.entities import ApiCredential
from app.schemas.api_access import API_SCOPES, ApiCredentialRead
from app.services.auth import token_hash


def decode_scopes(value: str) -> set[str]:
    try:
        scopes = json.loads(value)
    except (TypeError, ValueError):
        return set()
    if not isinstance(scopes, list):
        return set()
    return {str(scope) for scope in scopes if str(scope) in API_SCOPES}


def encode_scopes(scopes: list[str] | set[str]) -> str:
    return json.dumps(sorted(set(scopes)), separators=(",", ":"))


def issue_api_token() -> tuple[str, str, str]:
    raw = "zm_live_" + secrets.token_urlsafe(36)
    return raw, token_hash(raw), raw[:16]


def credential_read(item: ApiCredential) -> ApiCredentialRead:
    return ApiCredentialRead(
        id=item.id,
        name=item.name,
        token_prefix=item.token_prefix,
        scopes=sorted(decode_scopes(item.scopes_json)),
        created_at=item.created_at,
        last_used_at=item.last_used_at,
        expires_at=item.expires_at,
        revoked_at=item.revoked_at,
    )


def credential_is_active(item: ApiCredential) -> bool:
    now = datetime.now(UTC)
    return item.revoked_at is None and (item.expires_at is None or item.expires_at > now)
