"""Written consent from a parent or legal guardian, one row per minor per event."""
import enum

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Text, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class GuardianRelationship(str, enum.Enum):
    PARENT = "parent"
    LEGAL_GUARDIAN = "legal_guardian"


class GuardianLinkStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class GuardianConsent(Base):
    __tablename__ = "guardian_consents"

    id = Column(Integer, primary_key=True, index=True)
    minor_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    guardian_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)

    relationship_type = Column("relationship", String(20), nullable=False)  # GuardianRelationship
    guardian_name_typed = Column(String(255), nullable=False)  # typed full name = signature
    consent_text_version = Column(String(50), nullable=False)
    terms_version = Column(String(50), nullable=True)  # event terms accepted on the minor's behalf
    optional_email_consent = Column(Boolean, default=False, nullable=False)

    consented_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    withdrawn_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Evidence of the electronic signature; scrubbed after the security-log period.
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    minor = relationship("User", foreign_keys=[minor_user_id])
    guardian = relationship("User", foreign_keys=[guardian_user_id])

    __table_args__ = (
        Index("idx_guardian_consents_minor_event", "minor_user_id", "event_id"),
        Index("idx_guardian_consents_guardian", "guardian_user_id"),
    )

    @property
    def is_active(self) -> bool:
        return self.withdrawn_at is None

    def __repr__(self):
        return (f"<GuardianConsent(minor={self.minor_user_id}, guardian={self.guardian_user_id}, "
                f"event={self.event_id}, withdrawn={self.withdrawn_at is not None})>")
