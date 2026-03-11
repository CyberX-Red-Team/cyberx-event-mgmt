"""Agent task model for instance-side task execution."""
from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, Text, Index, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class AgentTask(Base):
    """Task dispatched to an instance agent."""

    __tablename__ = "agent_tasks"

    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("instances.id", ondelete="CASCADE"), nullable=False)
    task_type = Column(String(50), nullable=False, index=True)  # e.g. "cycle_vpn"
    payload = Column(JSON, nullable=True)  # Task-specific input
    status = Column(String(20), default="PENDING", nullable=False)  # PENDING, IN_PROGRESS, COMPLETED, FAILED
    result = Column(JSON, nullable=True)  # Task output
    error_message = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    instance = relationship("Instance", backref="agent_tasks")
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    __table_args__ = (
        Index("idx_agent_tasks_instance_status", "instance_id", "status"),
    )

    def __repr__(self):
        return f"<AgentTask(id={self.id}, instance_id={self.instance_id}, type={self.task_type}, status={self.status})>"
