from app.schemas.api_access import API_SCOPES, ApiCredentialCreate
from app.services.api_access import decode_scopes, encode_scopes, issue_api_token


def test_api_scope_roundtrip():
    encoded = encode_scopes({"participants:read", "collections:write"})
    assert decode_scopes(encoded) == {"participants:read", "collections:write"}


def test_api_token_is_prefixed_and_not_returned_as_hash():
    raw, hashed, prefix = issue_api_token()
    assert raw.startswith("zm_live_")
    assert prefix == raw[:16]
    assert hashed != raw
    assert len(hashed) == 64


def test_api_credential_rejects_unknown_scope():
    try:
        ApiCredentialCreate(name="ERP", scopes=["root:all"])
    except ValueError:
        pass
    else:
        raise AssertionError("unknown scope must be rejected")


def test_expected_public_api_scopes_exist():
    assert {"participants:read", "participants:write", "collections:read", "collections:write", "payments:read"} <= API_SCOPES
