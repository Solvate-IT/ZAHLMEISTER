import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StoreSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "store_subscriptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    product_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active", index=True)
    external_reference: Mapped[str | None] = mapped_column(String(320), unique=True)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_renew: Mapped[bool | None] = mapped_column(Boolean)
    environment: Mapped[str | None] = mapped_column(String(20))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    verification_data_encrypted: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("organization_id", "provider", name="uq_store_subscription_org_provider"),
        CheckConstraint(
            "provider IN ('admin','apple','google','mollie')",
            name="ck_store_subscriptions_provider",
        ),
        CheckConstraint(
            "status IN ('pending','active','grace_period','cancelled','expired','revoked','on_hold')",
            name="ck_store_subscriptions_status",
        ),
        Index("ix_store_subscriptions_org_status", "organization_id", "status"),
    )


class PlatformAdminAudit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_admin_audit"

    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
