"""Application settings model for dynamic configuration."""
from sqlalchemy import Column, String, Text, TIMESTAMP
from sqlalchemy.sql import func
from app.database import Base


class AppSetting(Base):
    """Application settings - key-value pairs for dynamic configuration."""

    __tablename__ = "app_settings"

    # Primary Key
    key = Column(String(100), primary_key=True)

    # Value (stored as text, can be JSON)
    value = Column(Text, nullable=False)

    # Description
    description = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<AppSetting(key={self.key}, value={self.value[:50]}...)>"
