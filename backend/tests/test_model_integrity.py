from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.channel_strategy import ParticipantChannelSetting
from app.models.entities import (
    ApiCredential,
    BankTransaction,
    Collection,
    CollectionParticipant,
    CommunicationChannelSetting,
    MessageTemplate,
    ParticipantList,
)
from app.models.platform import StoreSubscription


def _check_names(model) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }


def _index_names(model) -> set[str]:
    return {index.name for index in model.__table__.indexes if index.name}


def _unique_constraint_names(model) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name
    }


def test_participant_channel_constraints_match_database_contract() -> None:
    assert _check_names(ParticipantChannelSetting) >= {
        "ck_participant_channel_settings_channel",
        "ck_participant_channel_settings_availability",
    }


def test_collection_constraints_match_database_contract() -> None:
    assert Collection.__table__.c.communication_channel.default.arg == "auto"
    assert Collection.__table__.c.communication_mode.default.arg == "auto"
    assert _check_names(Collection) >= {
        "ck_collections_amount_positive",
        "ck_collections_communication_channel",
        "ck_collections_communication_mode",
    }
    assert "uq_collections_org_name" in _unique_constraint_names(Collection)
    assert "message_overrides_json" in Collection.__table__.c
    assert "message_body_override" not in Collection.__table__.c


def test_core_names_are_unique_per_organization() -> None:
    assert "uq_participant_lists_org_name" in _unique_constraint_names(ParticipantList)
    assert "uq_message_templates_org_name" in _unique_constraint_names(MessageTemplate)
    assert "uq_collections_org_name" in _unique_constraint_names(Collection)


def test_collection_participant_identity_is_unique() -> None:
    assert "uq_collection_participant_identity" in _unique_constraint_names(CollectionParticipant)
    assert "ck_collection_participant_reminder_count" in _check_names(CollectionParticipant)


def test_message_template_default_is_unique_per_organization() -> None:
    index = next(
        item
        for item in MessageTemplate.__table__.indexes
        if item.name == "uq_message_templates_org_default"
    )
    assert index.unique is True
    assert [column.name for column in index.columns] == ["organization_id"]
    assert index.dialect_options["postgresql"]["where"] is not None


def test_orm_metadata_preserves_required_schema_objects() -> None:
    assert "uq_api_credentials_token_hash" in _unique_constraint_names(ApiCredential)
    assert "ix_bank_transactions_sync_account" in _index_names(BankTransaction)
    assert "ix_collections_message_template_id" in _index_names(Collection)
    assert "ix_comm_channel_settings_connection" in _index_names(CommunicationChannelSetting)


def test_subscription_provider_and_status_are_database_constrained() -> None:
    assert _check_names(StoreSubscription) >= {
        "ck_store_subscriptions_provider",
        "ck_store_subscriptions_status",
    }
    assert "uq_store_subscription_org_provider" in _unique_constraint_names(StoreSubscription)
