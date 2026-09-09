import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BillingProfile(TimestampMixin, Base):
    __tablename__ = "billing_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    customer_type: Mapped[str] = mapped_column(String(20), nullable=False, default="consumer")
    given_name: Mapped[str | None] = mapped_column(String(120))
    family_name: Mapped[str | None] = mapped_column(String(120))
    organization_name: Mapped[str | None] = mapped_column(String(200))
    billing_email: Mapped[str] = mapped_column(String(320), nullable=False)
    street_and_number: Mapped[str] = mapped_column(String(240), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(40), nullable=False)
    city: Mapped[str] = mapped_column(String(160), nullable=False)
    region: Mapped[str | None] = mapped_column(String(160))
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    vat_number: Mapped[str | None] = mapped_column(String(40))
    organization_number: Mapped[str | None] = mapped_column(String(80))
    vat_validation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unverified")
    vat_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_billing_profiles_country", "country"),)


class BillingLegalEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_legal_entities"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    legal_name: Mapped[str] = mapped_column(String(240), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    billing_email: Mapped[str] = mapped_column(String(320), nullable=False)
    street_and_number: Mapped[str] = mapped_column(String(240), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(40), nullable=False)
    city: Mapped[str] = mapped_column(String(160), nullable=False)
    region: Mapped[str | None] = mapped_column(String(160))
    vat_number: Mapped[str | None] = mapped_column(String(40))
    organization_number: Mapped[str | None] = mapped_column(String(80))
    mollie_profile_id: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("char_length(country) = 2", name="ck_billing_legal_entity_country"),
        Index("ix_billing_legal_entity_active", "active"),
    )


class BillingTaxRegistration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_tax_registrations"

    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_legal_entities.id", ondelete="RESTRICT"), nullable=False
    )
    registration_type: Mapped[str] = mapped_column(String(30), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    registration_reference: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "registration_type IN ('vat','eu_oss','gst','sales_tax')",
            name="ck_billing_tax_registration_type",
        ),
        CheckConstraint("char_length(country) = 2", name="ck_billing_tax_registration_country"),
        UniqueConstraint(
            "legal_entity_id",
            "registration_type",
            "country",
            "registration_reference",
            name="uq_billing_tax_registration_identity",
        ),
        Index("ix_billing_tax_registration_active", "legal_entity_id", "active"),
    )


class BillingCycle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_cycles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("store_subscriptions.id", ondelete="SET NULL"), index=True
    )
    billing_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="prepared", index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="mollie")
    provider_environment: Mapped[str] = mapped_column(String(20), nullable=False)
    product_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tariff_version: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    tax_scheme: Mapped[str] = mapped_column(String(30), nullable=False)
    tax_treatment: Mapped[str] = mapped_column(String(40), nullable=False)
    tax_rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    recipient_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("operation IN ('initial','renewal')", name="ck_billing_cycle_operation"),
        CheckConstraint(
            "status IN ('prepared','payment_pending','paid','failed','cancelled')",
            name="ck_billing_cycle_status",
        ),
        CheckConstraint("provider IN ('mollie')", name="ck_billing_cycle_provider"),
        CheckConstraint("provider_environment IN ('test','live')", name="ck_billing_cycle_environment"),
        CheckConstraint("gross_amount >= 0", name="ck_billing_cycle_gross_nonnegative"),
        CheckConstraint("period_end > period_start", name="ck_billing_cycle_period"),
        CheckConstraint("retry_count >= 0", name="ck_billing_cycle_retry_nonnegative"),
        UniqueConstraint(
            "organization_id",
            "provider",
            "product_id",
            "period_start",
            name="uq_billing_cycle_org_provider_product_period",
        ),
        Index("ix_billing_cycle_due", "status", "period_start"),
    )


class BillingPaymentTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_payment_transactions"

    cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_cycles.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="mollie")
    provider_environment: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="reserved", index=True)
    sequence_type: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    provider_reference: Mapped[str | None] = mapped_column(String(200), unique=True, index=True)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("provider IN ('mollie')", name="ck_billing_payment_provider"),
        CheckConstraint("provider_environment IN ('test','live')", name="ck_billing_payment_environment"),
        CheckConstraint("attempt > 0", name="ck_billing_payment_attempt_positive"),
        CheckConstraint(
            "status IN ('reserved','open','pending','paid','failed','cancelled','expired')",
            name="ck_billing_payment_status",
        ),
        CheckConstraint("sequence_type IN ('first','recurring')", name="ck_billing_payment_sequence"),
        CheckConstraint("gross_amount >= 0", name="ck_billing_payment_gross_nonnegative"),
        UniqueConstraint("cycle_id", "attempt", name="uq_billing_payment_cycle_attempt"),
        Index("ix_billing_payment_cycle_status", "cycle_id", "status"),
    )


class BillingInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_invoices"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    billing_cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_cycles.id", ondelete="SET NULL"), index=True
    )
    payment_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_payment_transactions.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="mollie")
    product_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tariff_version: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    vat_scheme: Mapped[str] = mapped_column(String(30), nullable=False)
    tax_treatment: Mapped[str] = mapped_column(String(40), nullable=False)
    recipient_country: Mapped[str] = mapped_column(String(2), nullable=False)
    recipient_type: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_vat_number: Mapped[str | None] = mapped_column(String(40))
    seller_legal_name: Mapped[str | None] = mapped_column(String(240))
    seller_country: Mapped[str | None] = mapped_column(String(2))
    seller_vat_number: Mapped[str | None] = mapped_column(String(40))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True, index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="creating", index=True)
    payment_reference: Mapped[str | None] = mapped_column(String(200), index=True)
    payment_url: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "product_id",
            "period_start",
            name="uq_billing_invoice_org_provider_product_period",
        ),
        Index("ix_billing_invoice_org_period", "organization_id", "period_start"),
        Index("ix_billing_invoice_status_period", "status", "period_end"),
    )
