"""OpenStack Instance model."""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Instance(Base):
    """Tracked OpenStack VM instance."""

    __tablename__ = "instances"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    openstack_id = Column(String(100), unique=True, nullable=True)  # Nova server UUID
    status = Column(String(50), default="BUILDING", nullable=False)  # BUILDING, ACTIVE, ERROR, SHUTOFF, DELETED
    ip_address = Column(String(50), nullable=True)

    # Configuration used to create
    flavor_id = Column(String(100), nullable=False)
    image_id = Column(String(100), nullable=False)
    network_id = Column(String(100), nullable=False)
    key_name = Column(String(100), nullable=True)
    cloud_init_template_id = Column(Integer, ForeignKey("cloud_init_templates.id", ondelete="SET NULL"), nullable=True)

    # Optional associations
    event_id = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_to_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Metadata
    error_message = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)  # Soft delete

    # Relationships
    event = relationship("Event", backref="instances")
    assigned_to = relationship("User", foreign_keys=[assigned_to_user_id], backref="assigned_instances")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    cloud_init_template = relationship("CloudInitTemplate")

    def __repr__(self):
        return f"<Instance(id={self.id}, name={self.name}, status={self.status})>"
