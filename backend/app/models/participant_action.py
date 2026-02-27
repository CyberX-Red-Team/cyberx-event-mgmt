"""Participant action model for flexible task assignment."""
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class ActionType(str, enum.Enum):
    """Types of actions participants can be assigned."""
    IN_PERSON_ATTENDANCE = "in_person_attendance"
    SURVEY_COMPLETION = "survey_completion"
    ORIENTATION_RSVP = "orientation_rsvp"
    DOCUMENT_REVIEW = "document_review"
    CUSTOM = "custom"


class ActionStatus(str, enum.Enum):
    """Status of participant action."""
    PENDING = "pending"          # Awaiting response
    CONFIRMED = "confirmed"      # Participant confirmed
    DECLINED = "declined"        # Participant declined
    EXPIRED = "expired"          # Past deadline
    CANCELLED = "cancelled"      # Admin cancelled


class ParticipantAction(Base):
    """
    Flexible action/task assignment system for participants.

    Allows admins to assign confirm/deny tasks to specific participants
    or all participants for an event.
    """
    __tablename__ = "participant_actions"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Relationships
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Batch grouping (all actions from a single bulk create share the same batch_id)
    batch_id = Column(String(100), nullable=True, index=True)

    # Action Details
    action_type = Column(String(50), nullable=False, index=True)  # ActionType enum value
    title = Column(String(255), nullable=False)  # "Confirm In-Person Attendance"
    description = Column(Text, nullable=True)  # Optional detailed description

    # Status Tracking
    status = Column(String(20), default=ActionStatus.PENDING.value, nullable=False, index=True)

    # Response Details
    responded_at = Column(TIMESTAMP(timezone=True), nullable=True)
    response_note = Column(Text, nullable=True)  # Optional participant note

    # Deadline (optional)
    deadline = Column(TIMESTAMP(timezone=True), nullable=True)

    # Email Notification Tracking
    notification_sent = Column(Boolean, default=False)
    notification_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    email_template_id = Column(Integer, ForeignKey("email_templates.id", ondelete="SET NULL"), nullable=True)

    # Action-specific metadata (JSON for type-specific data)
    action_metadata = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="assigned_actions")
    event = relationship("Event", backref="participant_actions")
    created_by = relationship("User", foreign_keys=[created_by_id])
    email_template = relationship("EmailTemplate", foreign_keys=[email_template_id])

    def __repr__(self):
        return f"<ParticipantAction(id={self.id}, user_id={self.user_id}, type={self.action_type}, status={self.status})>"
