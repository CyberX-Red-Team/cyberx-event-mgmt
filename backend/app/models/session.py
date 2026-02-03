"""Session management model."""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, Text, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Session(Base):
    """Session model for user authentication."""

    __tablename__ = "sessions"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Session Token
    session_token = Column(String(255), unique=True, nullable=False, index=True)

    # User Reference
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # Session Info
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    ip_address = Column(String(45), nullable=True)  # Supports IPv6
    user_agent = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    # Relationships
    user = relationship("User", backref="sessions")

    # Indexes
    __table_args__ = (
        Index('idx_sessions_token', 'session_token'),
        Index('idx_sessions_user_id', 'user_id'),
        Index('idx_sessions_expires_at', 'expires_at'),
    )

    def __repr__(self):
        return f"<Session(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"
