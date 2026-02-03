"""Email template model for dynamic email templates."""
from sqlalchemy import Column, Integer, String, Boolean, Text, TIMESTAMP, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class EmailTemplate(Base):
    """Email template model for storing dynamic email templates."""

    __tablename__ = "email_templates"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Template identification
    name = Column(String(100), unique=True, nullable=False, index=True)  # e.g., "invite", "password"
    display_name = Column(String(255), nullable=False)  # e.g., "Invitation Email"
    description = Column(Text, nullable=True)

    # Email content
    subject = Column(String(500), nullable=False)
    html_content = Column(Text, nullable=False)
    text_content = Column(Text, nullable=True)

    # SendGrid integration
    sendgrid_template_id = Column(String(100), nullable=True)  # SendGrid dynamic template ID (e.g., "d-1234567890abcdef")

    # Variable metadata - list of variable names available for this template
    available_variables = Column(JSONB, default=list)  # e.g., ["first_name", "last_name", "email"]

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)  # System templates cannot be deleted

    # Audit fields
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now())
    created_by_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    created_by = relationship("User", backref="created_templates", foreign_keys=[created_by_id])

    # Indexes
    __table_args__ = (
        Index('idx_email_templates_is_active', 'is_active'),
        Index('idx_email_templates_is_system', 'is_system'),
    )

    def __repr__(self):
        return f"<EmailTemplate(id={self.id}, name={self.name}, display_name={self.display_name})>"
