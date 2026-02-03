"""Email queue model for event-based email batching."""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, Text, Index, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class EmailQueueStatus:
    """Email queue status constants."""
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EmailQueue(Base):
    """
    Queue for batching emails to be sent.

    Event-based approach: When a user is confirmed, an entry is added to this queue.
    A background processor sends emails in batches periodically.
    """

    __tablename__ = "email_queue"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # User Reference
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    # Email Details
    template_name = Column(String(100), nullable=False)  # invite, password, reminder, etc.
    recipient_email = Column(String(255), nullable=False, index=True)
    recipient_name = Column(String(500), nullable=True)

    # Custom Variables
    # Use JSON for cross-database compatibility (PostgreSQL and SQLite)
    custom_vars = Column(JSON, nullable=True)  # Template variables

    # Priority (lower number = higher priority)
    priority = Column(Integer, default=5, nullable=False, index=True)

    # Status
    status = Column(
        String(20),
        default=EmailQueueStatus.PENDING,
        nullable=False,
        index=True
    )

    # Processing
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    last_attempt_at = Column(TIMESTAMP(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # SendGrid Info
    sendgrid_message_id = Column(String(255), nullable=True)

    # Batch Info
    batch_id = Column(String(100), nullable=True, index=True)  # Group emails sent together
    processed_by = Column(String(100), nullable=True)  # Which worker processed it

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), index=True)
    scheduled_for = Column(TIMESTAMP(timezone=True), nullable=True, index=True)  # Delay sending
    processed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    sent_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", backref="queued_emails")

    # Indexes for efficient queries
    __table_args__ = (
        Index('idx_email_queue_status_priority', 'status', 'priority', 'created_at'),
        Index('idx_email_queue_scheduled', 'status', 'scheduled_for'),
        Index('idx_email_queue_processing', 'status', 'attempts', 'max_attempts'),
    )

    def __repr__(self):
        return f"<EmailQueue(id={self.id}, user_id={self.user_id}, template={self.template_name}, status={self.status})>"


class EmailBatchLog(Base):
    """Log of email batch processing runs."""

    __tablename__ = "email_batch_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Batch Info
    batch_id = Column(String(100), unique=True, nullable=False, index=True)
    batch_size = Column(Integer, nullable=False)

    # Processing Results
    total_processed = Column(Integer, default=0)
    total_sent = Column(Integer, default=0)
    total_failed = Column(Integer, default=0)

    # Timing
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # Worker Info
    processed_by = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)

    def __repr__(self):
        return f"<EmailBatchLog(batch_id={self.batch_id}, sent={self.total_sent}, failed={self.total_failed})>"
