"""Audit logging model."""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class AuditLog(Base):
    """Audit log model for tracking system activities."""

    __tablename__ = "audit_logs"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # User Reference
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # Action Details
    action = Column(String(100), nullable=False)  # LOGIN, LOGOUT, VPN_REQUEST, PASSWORD_RESET, etc.
    resource_type = Column(String(50), nullable=True)  # USER, VPN, EMAIL
    resource_id = Column(Integer, nullable=True)

    # Additional Details
    details = Column(JSONB, nullable=True)  # Flexible JSON storage for action-specific data

    # Request Info
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Timestamp
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", backref="audit_logs")

    # Indexes
    __table_args__ = (
        Index('idx_audit_logs_user_id', 'user_id'),
        Index('idx_audit_logs_action', 'action'),
        Index('idx_audit_logs_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, user_id={self.user_id})>"


class EmailEvent(Base):
    """Email event tracking model for SendGrid webhooks."""

    __tablename__ = "email_events"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # User Reference
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # Email Details
    email_to = Column(String(255), nullable=False)
    event_type = Column(String(50), nullable=False)  # delivered, opened, bounced, spam_report, etc.
    template_name = Column(String(100), nullable=True)

    # SendGrid IDs
    sendgrid_event_id = Column(String(255), nullable=True)
    sendgrid_message_id = Column(String(255), nullable=True)

    # Event Payload
    payload = Column(JSONB, nullable=True)  # Full webhook payload

    # Processing
    processed = Column(Boolean, default=False)

    # Timestamp
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", backref="email_events")

    # Indexes
    __table_args__ = (
        Index('idx_email_events_user_id', 'user_id'),
        Index('idx_email_events_type', 'event_type'),
        Index('idx_email_events_processed', 'processed'),
    )

    def __repr__(self):
        return f"<EmailEvent(id={self.id}, type={self.event_type}, to={self.email_to})>"


class VPNRequest(Base):
    """VPN request tracking model."""

    __tablename__ = "vpn_requests"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # User and VPN References
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    vpn_credential_id = Column(Integer, ForeignKey('vpn_credentials.id', ondelete='SET NULL'), nullable=True)

    # Request Details
    key_type = Column(String(20), nullable=False)  # cyber/kinetic
    status = Column(String(50), default='PENDING')  # PENDING, ALLOCATED, SENT, FAILED
    request_source = Column(String(50), nullable=True)  # PORTAL, DISCORD, WEBHOOK

    # Discord Integration
    discord_channel_id = Column(String(100), nullable=True)
    discord_message_id = Column(String(100), nullable=True)

    # Error Handling
    error_message = Column(Text, nullable=True)

    # Timestamps
    requested_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    processed_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", backref="vpn_requests")
    vpn_credential = relationship("VPNCredential", backref="vpn_requests")

    # Indexes
    __table_args__ = (
        Index('idx_vpn_requests_user_id', 'user_id'),
        Index('idx_vpn_requests_status', 'status'),
    )

    def __repr__(self):
        return f"<VPNRequest(id={self.id}, user_id={self.user_id}, status={self.status})>"
