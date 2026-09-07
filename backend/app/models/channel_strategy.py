import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CommunicationPreference(Base):
    __tablename__ = "communication_preferences"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    channel_order_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["email","whatsapp","sms","telegram"]',
    )


class ParticipantChannelSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "participant_channel_settings"

    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    availability: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_failure_reason: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "participant_id",
            "channel",
            name="uq_participant_channel_setting_participant_channel",
        ),
        Index("ix_participant_channel_settings_participant", "participant_id"),
    )
