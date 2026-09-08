from sqlalchemy import CheckConstraint

from app.models.channel_strategy import ParticipantChannelSetting
from app.models.entities import Collection, MessageTemplate


def _check_names(model) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }


def test_participant_channel_constraints_match_database_contract() -> None:
    assert _check_names(ParticipantChannelSetting) >= {
        "ck_participant_channel_settings_channel",
        "ck_participant_channel_settings_availability",
    }


def test_collection_communication_defaults_and_constraints_match_database_contract() -> None:
    assert Collection.__table__.c.communication_channel.default.arg == "auto"
    assert Collection.__table__.c.communication_mode.default.arg == "auto"
    assert _check_names(Collection) >= {
        "ck_collections_communication_channel",
        "ck_collections_communication_mode",
    }


def test_message_template_default_is_unique_per_organization() -> None:
    index = next(
        item
        for item in MessageTemplate.__table__.indexes
        if item.name == "uq_message_templates_org_default"
    )
    assert index.unique is True
    assert [column.name for column in index.columns] == ["organization_id"]
    assert index.dialect_options["postgresql"]["where"] is not None
