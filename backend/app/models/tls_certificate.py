"""TLS Certificate and CA Chain models for step-ca integration."""
import enum
from sqlalchemy import (
    Column, Integer, String, Boolean, TIMESTAMP, Text,
    ForeignKey, Index,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class CAChainStatus(str, enum.Enum):
    """CA chain step-ca sidecar status."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class TLSCertificateStatus(str, enum.Enum):
    """TLS certificate status."""
    ISSUED = "issued"
    REVOKED = "revoked"
    EXPIRED = "expired"


class CAChain(Base):
    """
    Certificate Authority chain configuration.

    Each CA chain maps to a dedicated step-ca sidecar instance on Render.
    Admin uploads root + intermediate CA files, which are stored encrypted in R2.
    """
    __tablename__ = "ca_chains"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)

    # R2 storage keys for CA files (private keys stored encrypted)
    root_cert_r2_key = Column(String(500), nullable=True)
    root_key_r2_key = Column(String(500), nullable=True)
    intermediate_cert_r2_key = Column(String(500), nullable=True)
    intermediate_key_r2_key = Column(String(500), nullable=True)

    # step-ca sidecar configuration
    render_service_id = Column(String(100), nullable=True)
    step_ca_url = Column(String(500), nullable=True)
    step_ca_provisioner = Column(String(100), default="cyberx")
    step_ca_status = Column(String(20), default=CAChainStatus.STOPPED.value, nullable=False)

    # Certificate defaults
    default_duration = Column(String(20), default="2160h")  # 90 days
    allow_wildcard = Column(Boolean, default=True)

    # Tracking
    created_by_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    event = relationship("Event", backref="ca_chains")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    certificates = relationship("TLSCertificate", back_populates="ca_chain")

    __table_args__ = (
        Index('idx_ca_chain_event_id', 'event_id'),
        Index('idx_ca_chain_status', 'step_ca_status'),
    )

    def __repr__(self):
        return f"<CAChain(id={self.id}, name={self.name}, status={self.step_ca_status})>"


class TLSCertificate(Base):
    """
    TLS certificate issued via step-ca.

    Tracks certificates requested by participants for domains
    validated against PowerDNS zones.
    """
    __tablename__ = "tls_certificates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    event_id = Column(Integer, ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    ca_chain_id = Column(Integer, ForeignKey('ca_chains.id', ondelete='CASCADE'), nullable=False)

    # Certificate details
    common_name = Column(String(255), nullable=False)
    sans = Column(Text, nullable=True)  # JSON array of SANs
    is_wildcard = Column(Boolean, default=False)
    serial_number = Column(String(100), nullable=True)
    fingerprint = Column(String(100), nullable=True)

    # R2 storage keys
    cert_bundle_r2_key = Column(String(500), nullable=True)  # cert + chain PEM
    private_key_r2_key = Column(String(500), nullable=True)  # encrypted private key

    # Status and lifecycle
    status = Column(String(20), default=TLSCertificateStatus.ISSUED.value, nullable=False)
    issued_at = Column(TIMESTAMP(timezone=True), nullable=True)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    revoked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    revocation_reason = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="tls_certificates")
    event = relationship("Event", backref="tls_certificates")
    ca_chain = relationship("CAChain", back_populates="certificates")

    __table_args__ = (
        Index('idx_tls_cert_user_id', 'user_id'),
        Index('idx_tls_cert_event_id', 'event_id'),
        Index('idx_tls_cert_ca_chain_id', 'ca_chain_id'),
        Index('idx_tls_cert_status', 'status'),
        Index('idx_tls_cert_common_name', 'common_name'),
    )

    def __repr__(self):
        return (
            f"<TLSCertificate(id={self.id}, cn={self.common_name}, "
            f"status={self.status})>"
        )
