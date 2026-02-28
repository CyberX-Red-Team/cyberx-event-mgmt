"""CPE Certificate model for tracking issued certificates."""
import enum
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, TIMESTAMP, Text,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class CertificateStatus(str, enum.Enum):
    """Certificate status enumeration."""
    ISSUED = "issued"
    REVOKED = "revoked"


class CPECertificate(Base):
    """
    CPE (Continuing Professional Education) certificate record.

    Tracks certificates issued to participants who met engagement criteria
    during a CyberX event. One certificate per user per event.
    """
    __tablename__ = "cpe_certificates"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # References
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    issued_by_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # Certificate details
    certificate_number = Column(String(50), unique=True, nullable=False, index=True)  # e.g. "CX-2026-0042"
    cpe_hours = Column(Float, default=32.0, nullable=False)
    status = Column(String(20), default=CertificateStatus.ISSUED.value, nullable=False, index=True)

    # Eligibility snapshot (recorded at issuance for audit trail)
    has_nextcloud_login = Column(Boolean, default=False, nullable=False)
    has_powerdns_login = Column(Boolean, default=False, nullable=False)
    has_vpn_assigned = Column(Boolean, default=False, nullable=False)

    # PDF storage
    pdf_storage_key = Column(String(500), nullable=True)  # R2 object key
    pdf_generated_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Revocation
    revoked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    revoked_by_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    revocation_reason = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="cpe_certificates")
    event = relationship("Event", backref="cpe_certificates")
    issued_by = relationship("User", foreign_keys=[issued_by_user_id])
    revoked_by = relationship("User", foreign_keys=[revoked_by_user_id])

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint('user_id', 'event_id', name='uq_cpe_user_event'),
        Index('idx_cpe_user_id', 'user_id'),
        Index('idx_cpe_event_id', 'event_id'),
        Index('idx_cpe_status', 'status'),
    )

    def __repr__(self):
        return (
            f"<CPECertificate(id={self.id}, number={self.certificate_number}, "
            f"user_id={self.user_id}, status={self.status})>"
        )
