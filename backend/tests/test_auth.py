from app.services.auth import hash_password, normalize_email, token_hash, verify_password


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("very-secret-password")
    assert hashed != "very-secret-password"
    assert verify_password(hashed, "very-secret-password")
    assert not verify_password(hashed, "wrong-password")


def test_email_and_token_normalization() -> None:
    assert normalize_email(" User@Example.COM ") == "user@example.com"
    assert token_hash("abc") == token_hash("abc")
    assert token_hash("abc") != token_hash("def")


def test_auth_response_exposes_organization_name() -> None:
    import uuid

    from app.models.entities import Organization, User
    from app.services.auth import auth_response

    organization_id = uuid.uuid4()
    organization = Organization(
        id=organization_id,
        name="Muster Verein",
        locale="de-AT",
        currency="EUR",
    )
    user = User(
        id=uuid.uuid4(),
        organization_id=organization_id,
        email="anna@example.com",
        display_name="Anna",
        password_hash="unused",
    )

    response = auth_response("token", user, organization)

    assert response.user.organization_name == "Muster Verein"
