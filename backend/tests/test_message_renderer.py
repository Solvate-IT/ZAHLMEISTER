import json
from decimal import Decimal

import pytest

from app.models.entities import Collection, CollectionParticipant, CommunicationMessage, Organization, Participant
from app.services.message_renderer import canonical_from_stored_message, render_collection_message


@pytest.mark.asyncio
async def test_collection_message_is_channel_and_provider_independent() -> None:
    organization = Organization(
        name="Test",
        locale="de-AT",
        currency="EUR",
        bank_account_name=None,
        bank_iban=None,
        bank_bic=None,
        message_include_payment_link=True,
        message_include_payment_qr=False,
    )
    collection = Collection(
        name="Ausflug",
        amount=Decimal("12.00"),
        currency="EUR",
        message_template_id=None,
        message_body_override=None,
        message_include_payment_link=None,
        message_include_payment_qr=None,
        due_at=None,
    )
    cp = CollectionParticipant(payment_reference="ZM-ABC", public_token="token")
    participant = Participant(name="Anna Muster")

    content = await render_collection_message(
        None,  # no DB lookup is needed when no saved template is selected
        collection=collection,
        collection_participant=cp,
        participant=participant,
        organization=organization,
    )

    assert content.subject == "Ausflug"
    assert "Anna" in content.text
    assert "12.00 EUR" in content.text
    assert "ZM-ABC" in content.text
    assert "?pay=token" in content.text
    assert content.payment_qr_url is None


def test_stored_message_rehydrates_exact_canonical_content() -> None:
    metadata = {
        "payment_link_included": True,
        "payment_qr_requested": True,
        "payment_qr_included": True,
        "payment_qr_url": "https://example.test/qr.png",
        "payment_qr_payload": "BCD\n002\n1\nSCT",
    }
    stored = CommunicationMessage(
        subject="Ausflug",
        body="Bitte 12 EUR bezahlen",
        metadata_json=json.dumps(metadata),
    )

    content = canonical_from_stored_message(stored)

    assert content.subject == stored.subject
    assert content.text == stored.body
    assert content.payment_qr_url == metadata["payment_qr_url"]
    assert content.payment_qr_payload == metadata["payment_qr_payload"]

@pytest.mark.asyncio
async def test_collection_message_applies_link_and_qr_options_once() -> None:
    organization = Organization(
        name="Test",
        locale="de-AT",
        currency="EUR",
        bank_account_name="Max Muster",
        bank_iban="AT611904300234573201",
        bank_bic=None,
        message_include_payment_link=False,
        message_include_payment_qr=True,
    )
    collection = Collection(
        name="Material",
        amount=Decimal("8.00"),
        currency="EUR",
        message_template_id=None,
        message_body_override=None,
        message_include_payment_link=None,
        message_include_payment_qr=None,
        due_at=None,
    )
    cp = CollectionParticipant(payment_reference="ZM-QR", public_token="qr-token")
    participant = Participant(name="Anna Muster")

    content = await render_collection_message(
        None,
        collection=collection,
        collection_participant=cp,
        participant=participant,
        organization=organization,
    )

    assert "?pay=qr-token" not in content.text
    assert "{{payment_link}}" not in content.text
    assert content.payment_qr_requested is True
    assert content.payment_qr_payload is not None
    assert content.payment_qr_url and content.payment_qr_url.endswith("/qr.png")
