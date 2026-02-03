"""Email workflow configuration model."""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, Text, Index, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class EmailWorkflow(Base):
    """
    Configuration for automated email workflows.

    Defines which email template to use for specific trigger events,
    allowing admins to configure automation without code changes.
    """

    __tablename__ = "email_workflows"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Workflow Identification
    name = Column(String(100), unique=True, nullable=False, index=True)  # e.g., "user_confirmation"
    display_name = Column(String(255), nullable=False)  # e.g., "User Confirmation Email"
    description = Column(Text, nullable=True)  # What this workflow does

    # Trigger Configuration
    trigger_event = Column(String(100), nullable=False, index=True)  # e.g., "user_confirmed", "vpn_assigned"

    # Email Configuration
    template_name = Column(String(100), nullable=False)  # Which EmailTemplate to use
    priority = Column(Integer, default=5, nullable=False)  # Queue priority (1=highest, 10=lowest)

    # Custom Variables (merged with event data)
    # Use JSON for cross-database compatibility (PostgreSQL and SQLite)
    custom_vars = Column(JSON, nullable=True, default=dict)  # Default template variables

    # Scheduling (optional)
    delay_minutes = Column(Integer, nullable=True)  # Delay before sending (null = immediate)

    # Status
    is_enabled = Column(Boolean, default=True, nullable=False, index=True)
    is_system = Column(Boolean, default=False, nullable=False)  # True for built-in workflows

    # Audit
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), onupdate=func.now(), nullable=True)
    created_by_id = Column(Integer, nullable=True)  # User who created this workflow

    # Indexes
    __table_args__ = (
        Index('idx_workflow_trigger_enabled', 'trigger_event', 'is_enabled'),
    )

    def __repr__(self):
        return f"<EmailWorkflow(name={self.name}, trigger={self.trigger_event}, enabled={self.is_enabled})>"


class WorkflowTriggerEvent:
    """Constants for workflow trigger events."""

    # User Events
    USER_CREATED = "user_created"
    USER_CONFIRMED = "user_confirmed"
    USER_ACTIVATED = "user_activated"
    USER_DEACTIVATED = "user_deactivated"

    # Credential Events
    PASSWORD_RESET = "password_reset"
    VPN_ASSIGNED = "vpn_assigned"

    # Event Participation
    PARTICIPATION_CONFIRMED = "participation_confirmed"
    EVENT_REMINDER = "event_reminder"
    EVENT_STARTED = "event_started"
    EVENT_ENDED = "event_ended"

    # Feedback
    SURVEY_REQUEST = "survey_request"

    # Admin Actions
    BULK_INVITE = "bulk_invite"
    CUSTOM_EMAIL = "custom_email"
