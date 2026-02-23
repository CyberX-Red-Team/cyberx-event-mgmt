"""Instance Template model for reusable instance configurations."""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


class InstanceTemplate(Base):
    """Instance template for bundling common instance configurations.

    Templates combine provider settings, cloud-init, licenses, and resource
    limits into named configurations (e.g., "Hexio teamserver", "Redirector")
    that participants can use for self-service provisioning.
    """
    __tablename__ = "instance_templates"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Identity
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # Provider configuration
    provider = Column(String(50), default="openstack", nullable=False)

    # OpenStack-specific fields
    flavor_id = Column(String(100), nullable=True)
    network_id = Column(String(100), nullable=True)

    # DigitalOcean-specific fields
    provider_size_slug = Column(String(100), nullable=True)
    provider_region = Column(String(100), nullable=True)

    # Common fields (image required)
    image_id = Column(String(100), nullable=False)

    # Template references
    cloud_init_template_id = Column(
        Integer,
        ForeignKey("cloud_init_templates.id", ondelete="SET NULL"),
        nullable=True
    )
    license_product_id = Column(
        Integer,
        ForeignKey("license_products.id", ondelete="SET NULL"),
        nullable=True
    )

    # Event association (required - templates are scoped to events)
    event_id = Column(
        Integer,
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Metadata
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Relationships
    event = relationship("Event", backref="instance_templates")
    cloud_init_template = relationship("CloudInitTemplate")
    license_product = relationship("LicenseProduct")
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f"<InstanceTemplate(id={self.id}, name='{self.name}', provider='{self.provider}', event_id={self.event_id})>"
