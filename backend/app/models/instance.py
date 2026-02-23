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
    # Cloud provider: openstack, digitalocean
    provider = Column(String(50), default="openstack", nullable=False, index=True)
    # Provider's instance UUID/ID
    provider_instance_id = Column(String(100), unique=True, nullable=True)
    # BUILDING, ACTIVE, ERROR, SHUTOFF, DELETED
    status = Column(String(50), default="BUILDING", nullable=False)
    ip_address = Column(String(50), nullable=True)
    # VPN IP from cloud-init config (if applicable)
    vpn_ip = Column(String(50), nullable=True)
    # SHA-256 hash of single-use token for cloud-init
    vpn_config_token = Column(String(255), nullable=True)
    # Token expiry (3 minutes)
    vpn_config_token_expires_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Configuration used to create (provider-specific fields)
    # OpenStack fields
    flavor_id = Column(String(100), nullable=True)  # OpenStack flavor ID
    network_id = Column(String(100), nullable=True)  # OpenStack network ID

    # DigitalOcean fields
    # DigitalOcean size slug (e.g., 's-1vcpu-1gb')
    provider_size_slug = Column(String(100), nullable=True)
    # DigitalOcean region (e.g., 'nyc1')
    provider_region = Column(String(100), nullable=True)

    # Common fields
    image_id = Column(String(100), nullable=False)
    key_name = Column(String(100), nullable=True)
    cloud_init_template_id = Column(Integer, ForeignKey("cloud_init_templates.id", ondelete="SET NULL"), nullable=True)
    license_product_id = Column(Integer, ForeignKey("license_products.id", ondelete="SET NULL"), nullable=True, index=True)
    instance_template_id = Column(Integer, ForeignKey("instance_templates.id", ondelete="SET NULL"), nullable=True, index=True)

    # Optional associations
    event_id = Column(Integer, ForeignKey("events.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_to_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Metadata
    error_message = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Participant self-service fields
    visibility = Column(String(20), default="private", nullable=False, index=True)  # private, share, public
    notes = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)  # Soft delete

    # Relationships
    event = relationship("Event", backref="instances")
    assigned_to = relationship("User", foreign_keys=[assigned_to_user_id], backref="assigned_instances")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    cloud_init_template = relationship("CloudInitTemplate")
    license_product = relationship("LicenseProduct", backref="instances")
    instance_template = relationship("InstanceTemplate", backref="instances")

    def __repr__(self):
        return f"<Instance(id={self.id}, name={self.name}, status={self.status})>"
