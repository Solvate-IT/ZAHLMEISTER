from app.schemas.workflow import ParticipantUpdate
from app.api.routes.participant_lists import _participant_values


def test_participant_update_normalizes_name() -> None:
    payload = ParticipantUpdate(name="  Anna   Muster  ", email="anna@example.com")
    assert payload.name == "Anna Muster"
    assert payload.email == "anna@example.com"


def test_participant_save_normalizes_phone_before_duplicate_detection() -> None:
    payload = ParticipantUpdate(name="Anna Muster", phone="0660 1234567")
    _, phone, duplicate_key = _participant_values(payload, "AT")
    assert phone == duplicate_key == "+436601234567"
