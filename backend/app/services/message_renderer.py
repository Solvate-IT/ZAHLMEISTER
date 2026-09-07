import json
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import (
    Collection,
    CollectionParticipant,
    CommunicationMessage,
    MessageTemplate,
    Organization,
    Participant,
)
from app.services.payments import epc_qr_payload, public_payment_qr_url, public_payment_url
from app.services.templates import (
    default_template_body,
    message_values,
    normalize_translations,
    render_template,
    template_body_for_locale,
)


@dataclass(frozen=True)
class CanonicalMessage:
    """Provider-independent message generated exactly once for one recipient."""

    subject: str
    text: str
    payment_link_included: bool
    payment_qr_requested: bool
    payment_qr_url: str | None = None
    payment_qr_payload: str | None = None

    @property
    def payment_qr_included(self) -> bool:
        return self.payment_qr_payload is not None

    def metadata_json(self) -> str:
        return json.dumps(
            {
                "payment_link_included": self.payment_link_included,
                "payment_qr_requested": self.payment_qr_requested,
                "payment_qr_included": self.payment_qr_included,
                "payment_qr_url": self.payment_qr_url,
                "payment_qr_payload": self.payment_qr_payload,
            }
        )


def _message_options(collection: Collection, organization: Organization) -> tuple[bool, bool]:
    include_link = (
        collection.message_include_payment_link
        if collection.message_include_payment_link is not None
        else organization.message_include_payment_link
    )
    include_qr = (
        collection.message_include_payment_qr
        if collection.message_include_payment_qr is not None
        else organization.message_include_payment_qr
    )
    return bool(include_link), bool(include_qr)


async def render_collection_message(
    session: AsyncSession,
    *,
    collection: Collection,
    collection_participant: CollectionParticipant,
    participant: Participant,
    organization: Organization,
) -> CanonicalMessage:
    """Render one canonical message independent of channel and provider."""

    template_body = collection.message_body_override
    if template_body is None and collection.message_template_id is not None:
        template = await session.get(MessageTemplate, collection.message_template_id)
        if template is not None:
            template_body = template_body_for_locale(
                normalize_translations(template.translations_json), organization.locale
            )
    body = template_body or default_template_body(organization.locale)

    include_link, include_qr = _message_options(collection, organization)
    if not include_link:
        body = "\n".join(
            line for line in body.splitlines() if "{{payment_link}}" not in line
        )

    payment_url = public_payment_url(
        settings.public_app_url, collection_participant.public_token
    )
    values = message_values(
        participant_name=participant.name,
        collection_name=collection.name,
        amount=f"{Decimal(collection.amount):.2f}",
        currency=collection.currency,
        payment_url=payment_url if include_link else "",
        payment_reference=collection_participant.payment_reference,
        due_at=collection.due_at,
    )
    text = render_template(body, values)

    qr_payload: str | None = None
    qr_url: str | None = None
    if include_qr and organization.bank_account_name and organization.bank_iban:
        qr_payload = epc_qr_payload(
            account_name=organization.bank_account_name,
            iban=organization.bank_iban,
            bic=organization.bank_bic,
            amount=collection.amount,
            currency=collection.currency,
            reference=collection_participant.payment_reference,
        )
        if qr_payload is not None:
            qr_url = public_payment_qr_url(
                settings.public_app_url, collection_participant.public_token
            )

    return CanonicalMessage(
        subject=collection.name,
        text=text,
        payment_link_included=include_link,
        payment_qr_requested=include_qr,
        payment_qr_url=qr_url,
        payment_qr_payload=qr_payload,
    )


def canonical_from_stored_message(message: CommunicationMessage) -> CanonicalMessage:
    """Rehydrate the already-rendered canonical message for transport only."""

    if not message.body:
        raise ValueError("Stored communication message has no rendered body")
    try:
        metadata = json.loads(message.metadata_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return CanonicalMessage(
        subject=message.subject or "",
        text=message.body,
        payment_link_included=bool(metadata.get("payment_link_included", False)),
        payment_qr_requested=bool(metadata.get("payment_qr_requested", False)),
        payment_qr_url=(str(metadata["payment_qr_url"]) if metadata.get("payment_qr_url") else None),
        payment_qr_payload=(
            str(metadata["payment_qr_payload"]) if metadata.get("payment_qr_payload") else None
        ),
    )
