import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
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


class BillingInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_invoices"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="mollie")
    product_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tariff_version: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    vat_scheme: Mapped[str] = mapped_column(String(30), nullable=False)
    tax_treatment: Mapped[str] = mapped_column(String(40), nullable=False)
    recipient_country: Mapped[str] = mapped_column(String(2), nullable=False)
    recipient_type: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_vat_number: Mapped[str | None] = mapped_column(String(40))
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
