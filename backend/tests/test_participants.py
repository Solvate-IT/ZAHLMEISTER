from app.schemas.workflow import ParticipantUpdate


def test_participant_update_normalizes_name() -> None:
    payload = ParticipantUpdate(name="  Anna   Muster  ", email="anna@example.com")
    assert payload.name == "Anna Muster"
    assert payload.email == "anna@example.com"
