import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

_SUPPORTED_LOCALES_SQL = (
    "'bg','hr','cs','da','nl','en','et','fi','fr','de','el','hu',"
    "'ga','it','lv','lt','mt','pl','pt','ro','sk','sl','es','sv'"
)


class ParticipantPreference(Base):
    __tablename__ = "participant_preferences"

    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("participants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    locale: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"locale IN ({_SUPPORTED_LOCALES_SQL})",
            name="ck_participant_preferences_locale",
        ),
    )
