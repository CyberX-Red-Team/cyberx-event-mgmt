"""Scheduler status model for tracking background worker health."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from app.database import Base


class SchedulerStatus(Base):
    """Tracks the status of the background scheduler service."""

    __tablename__ = "scheduler_status"

    id = Column(Integer, primary_key=True)
    service_name = Column(String(100), nullable=False, unique=True, index=True)
    is_running = Column(Boolean, nullable=False, default=False)
    jobs = Column(JSON, nullable=False, default=list)
    last_heartbeat = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<SchedulerStatus(service={self.service_name}, running={self.is_running}, jobs={len(self.jobs)})>"
