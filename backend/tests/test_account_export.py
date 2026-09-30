"""GDPR data export (Art. 15/20): it must build for a workspace with real data.

Every category is filled with a real ORM instance, so an export column that reads
an attribute the model no longer has fails here instead of with HTTP 500 for the
customer (as it did after message_body_override was replaced by
message_overrides_json).
"""
import csv
import io
import json
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.routes import account
from app.models.channel_strategy import CommunicationPreference, ParticipantChannelSetting
from app.models.entities import (
    ApiCredential,
    BankStatementImport,
    BankSyncAccount,
    BankSyncConnection,
    BankTransaction,
    Collection,
    CollectionParticipant,
    CommunicationChannelSetting,
    CommunicationConnection,
    CommunicationMessage,
    MessageTemplate,
    OnlinePaymentAttempt,
    OnlinePaymentConnection,
    Organization,
    Participant,
    ParticipantList,
    Payment,
    User,
)
from app.models.participant_preferences import ParticipantPreference
from app.models.platform import StoreSubscription


def _with_id(instance):
    instance.id = uuid4()
    return instance


@pytest.mark.asyncio
async def test_export_builds_for_a_workspace_with_every_kind_of_record(monkeypatch) -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    organization = _with_id(Organization(name="Verein", locale="de-AT", currency="EUR"))
    user = _with_id(
        User(
            organization_id=organization.id,
            email="anna@example.test",
            display_name="Anna",
            email_verified_at=now,
        )
    )
    participant_list = _with_id(ParticipantList(organization_id=organization.id, name="Klasse 3b"))
    participant = _with_id(Participant(list_id=participant_list.id, name="Ben", email="ben@example.test"))
    overrides = json.dumps({"de": "Hallo {{name}}", "en": "Hello {{name}}"})
    collection = _with_id(
        Collection(
            organization_id=organization.id,
            participant_list_id=participant_list.id,
            name="Ausflug",
            amount=Decimal("20.00"),
            currency="EUR",
            status="active",
            communication_channel="auto",
            message_overrides_json=overrides,
            reminder_rules_json="[]",
        )
    )
    cp = _with_id(
        CollectionParticipant(
            collection_id=collection.id,
            participant_id=participant.id,
            payment_reference="ZM-1",
            public_token="token",
            status="open",
            reminder_count=0,
        )
    )
    rows = (
        [participant_list],
        [participant],
        [ParticipantPreference(participant_id=participant.id, locale="de")],
        [_with_id(ParticipantChannelSetting(participant_id=participant.id, channel="email"))],
        [collection],
        [cp],
        [_with_id(Payment(collection_participant_id=cp.id, amount=Decimal("20.00"), currency="EUR", method="manual", booked_at=now))],
        [
            _with_id(
                CommunicationMessage(
                    organization_id=organization.id,
                    collection_id=collection.id,
                    collection_participant_id=cp.id,
                    kind="initial",
                    channel="email",
                    status="sent",
                )
            )
        ],
        [_with_id(MessageTemplate(organization_id=organization.id, name="Standard"))],
        CommunicationPreference(organization_id=organization.id),
        [_with_id(CommunicationConnection(organization_id=organization.id, provider="infobip"))],
        [_with_id(CommunicationChannelSetting(organization_id=organization.id, channel="email"))],
        [_with_id(ApiCredential(organization_id=organization.id, name="ERP"))],
        [_with_id(BankStatementImport(organization_id=organization.id, filename="a.csv", format="csv"))],
        [_with_id(BankTransaction(organization_id=organization.id, booked_at=now, amount=Decimal("20.00"), currency="EUR"))],
        [_with_id(BankSyncConnection(organization_id=organization.id, provider="ponto"))],
        [_with_id(BankSyncAccount(organization_id=organization.id, external_id="acc-1"))],
        [_with_id(OnlinePaymentConnection(organization_id=organization.id, provider="mollie"))],
        [_with_id(OnlinePaymentAttempt(organization_id=organization.id, collection_participant_id=cp.id, provider="mollie"))],
        [_with_id(StoreSubscription(organization_id=organization.id, provider="mollie", status="active"))],
    )

    async def export_rows(_session, organization_id):
        assert organization_id == organization.id
        return rows

    async def get(model, _id):
        return organization if model is Organization else None

    monkeypatch.setattr(account, "_export_rows", export_rows)
    response = await account.export_account_data(user=user, session=SimpleNamespace(get=get))

    assert response.media_type == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.body))
    assert "collections.csv" in archive.namelist()
    exported = list(csv.DictReader(io.StringIO(archive.read("collections.csv").decode("utf-8-sig"))))
    assert exported[0]["name"] == "Ausflug"
    assert json.loads(exported[0]["message_overrides_json"]) == json.loads(overrides)
