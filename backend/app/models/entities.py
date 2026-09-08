import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="de-AT")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    bank_account_name: Mapped[str | None] = mapped_column(String(200))
    bank_iban: Mapped[str | None] = mapped_column(String(34))
    bank_bic: Mapped[str | None] = mapped_column(String(11))
    message_include_payment_link: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    message_include_payment_qr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    api_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ApiCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_credentials"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        Index("ix_api_credentials_org_created", "organization_id", "created_at"),
    )


class AccountActionToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "account_action_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_account_action_tokens_user_purpose", "user_id", "purpose"),)


class ParticipantList(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "participant_lists"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (Index("ix_participant_lists_org_name", "organization_id", "name"),)


class Participant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "participants"

    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("participant_lists.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    channel_addresses_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    __table_args__ = (Index("ix_participants_list_name", "list_id", "name"),)


class CommunicationConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "communication_connections"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(30), nullable=False, default="oauth")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="connected", index=True)
    account_label: Mapped[str | None] = mapped_column(String(320))
    account_key: Mapped[str | None] = mapped_column(String(120), index=True)
    encrypted_config: Mapped[str | None] = mapped_column(Text)
    webhook_key: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_comm_connections_org_provider", "organization_id", "provider"),
    )


class CommunicationChannelSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "communication_channel_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="external")
    provider: Mapped[str | None] = mapped_column(String(40))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("communication_connections.id", ondelete="SET NULL")
    )
    sender: Mapped[str | None] = mapped_column(String(320))
    encrypted_config: Mapped[str | None] = mapped_column(Text)
    sync_cursor: Mapped[str | None] = mapped_column(String(200))
    webhook_key: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_tested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("organization_id", "channel", name="uq_comm_channel_org_channel"),
        Index("ix_comm_channel_settings_org", "organization_id"),
    )


class MessageTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "message_templates"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    translations_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_message_templates_org", "organization_id"),
        Index("ix_message_templates_org_name", "organization_id", "name"),
        Index(
            "uq_message_templates_org_default",
            "organization_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class Collection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collections"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    participant_list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("participant_lists.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    communication_channel: Mapped[str] = mapped_column(String(30), nullable=False, default="auto")
    communication_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    message_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_templates.id", ondelete="SET NULL")
    )
    message_body_override: Mapped[str | None] = mapped_column(Text)
    reminder_rules_json: Mapped[str] = mapped_column(Text, nullable=False, default='[{"type":"after_send","days":5}]')
    message_include_payment_link: Mapped[bool | None] = mapped_column(Boolean)
    message_include_payment_qr: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (
        CheckConstraint(
            "communication_channel IN ('auto','email','whatsapp','sms','telegram')",
            name="ck_collections_communication_channel",
        ),
        CheckConstraint(
            "communication_mode = 'auto'",
            name="ck_collections_communication_mode",
        ),
        Index("ix_collections_org_created", "organization_id", "created_at"),
    )


class CollectionParticipant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collection_participants"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False
    )
    payment_reference: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    public_token: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open", index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initial_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_count: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        Index("ix_collection_participants_collection_status", "collection_id", "status"),
    )


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"

    collection_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_participants.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50))
    external_reference: Mapped[str | None] = mapped_column(String(200), index=True)
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)


class OnlinePaymentConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "online_payment_connections"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="mollie")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="connecting", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    account_label: Mapped[str | None] = mapped_column(String(320))
    profile_id: Mapped[str | None] = mapped_column(String(120))
    encrypted_config: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "provider", name="uq_online_payment_connection_org_provider"
        ),
        Index("ix_online_payment_connections_org_provider", "organization_id", "provider"),
    )


class OnlinePaymentAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "online_payment_attempts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    collection_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("collection_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("online_payment_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200), index=True)
    webhook_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="creating", index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    checkout_url: Mapped[str | None] = mapped_column(Text)
    payment_method: Mapped[str | None] = mapped_column(String(80))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "ix_online_payment_attempts_participant_created",
            "collection_participant_id",
            "created_at",
        ),
        Index(
            "ix_online_payment_attempts_connection_external",
            "connection_id",
            "external_id",
        ),
    )


class CommunicationMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "communication_messages"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    collection_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_participants.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False, default="email")
    delivery_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="outgoing")
    sender: Mapped[str | None] = mapped_column(String(320))
    recipient: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", index=True)
    provider: Mapped[str | None] = mapped_column(String(40))
    external_id: Mapped[str | None] = mapped_column(String(500), index=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(500), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_communication_messages_collection_participant", "collection_participant_id", "created_at"),
    )


class BankSyncConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bank_sync_connections"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="ponto")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="connecting", index=True)
    account_label: Mapped[str | None] = mapped_column(String(320))
    encrypted_config: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("organization_id", "provider", name="uq_bank_sync_connection_org_provider"),
        Index("ix_bank_sync_connections_org_provider", "organization_id", "provider"),
    )


class BankSyncAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bank_sync_accounts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_sync_connections.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str | None] = mapped_column(String(320))
    iban: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str | None] = mapped_column(String(3))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_bank_sync_account_external"),
        Index("ix_bank_sync_accounts_org", "organization_id"),
    )


class BankStatementImport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bank_statement_imports"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    format: Mapped[str] = mapped_column(String(30), nullable=False)
    transaction_count: Mapped[int] = mapped_column(nullable=False, default=0)
    auto_matched_count: Mapped[int] = mapped_column(nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(nullable=False, default=0)
    unmatched_count: Mapped[int] = mapped_column(nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (Index("ix_bank_imports_org_created", "organization_id", "created_at"),)


class BankTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bank_transactions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_statement_imports.id", ondelete="CASCADE")
    )
    bank_sync_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_sync_accounts.id", ondelete="SET NULL")
    )
    source_provider: Mapped[str | None] = mapped_column(String(40))
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    counterparty_name: Mapped[str | None] = mapped_column(String(300))
    reference: Mapped[str | None] = mapped_column(Text)
    bank_transaction_id: Mapped[str | None] = mapped_column(String(300))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="unmatched", index=True)
    candidate_collection_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collection_participants.id", ondelete="SET NULL")
    )
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    match_reason: Mapped[str | None] = mapped_column(String(200))
    applied_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL")
    )
    raw_details: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("organization_id", "fingerprint", name="uq_bank_transaction_org_fingerprint"),
        Index("ix_bank_transactions_import_status", "import_id", "status"),
    )


class RuntimeHeartbeat(Base):
    __tablename__ = "runtime_heartbeats"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    details_json: Mapped[str | None] = mapped_column(Text)


class ScheduledJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_jobs"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    job_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_jobs_due", "status", "scheduled_at"),)
