"""License management models."""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class LicenseProduct(Base):
    """A licensed product (e.g., Hexio C2). Admin-managed via UI."""

    __tablename__ = "license_products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    license_blob = Column(Text, nullable=False)
    max_concurrent = Column(Integer, default=2, nullable=False)  # Max simultaneous installs
    slot_ttl = Column(Integer, default=7200, nullable=False)  # Slot expiry in seconds
    token_ttl = Column(Integer, default=7200, nullable=False)  # Token expiry in seconds
    is_active = Column(Boolean, default=True, nullable=False)

    # Optional: file to download (used by cloud-init template rendering)
    download_filename = Column(String(500), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    tokens = relationship("LicenseToken", back_populates="product", cascade="all, delete-orphan")
    slots = relationship("LicenseSlot", back_populates="product", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<LicenseProduct(id={self.id}, name={self.name})>"


class LicenseToken(Base):
    """Short-lived, single-use license token. Generated per-request."""

    __tablename__ = "license_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA-256

    # Product association
    product_id = Column(Integer, ForeignKey("license_products.id", ondelete="CASCADE"), nullable=False, index=True)

    # Usage tracking
    used = Column(Boolean, default=False, nullable=False)
    used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    used_by_ip = Column(String(50), nullable=True)

    # Optional instance association
    instance_id = Column(Integer, ForeignKey("instances.id", ondelete="SET NULL"), nullable=True, index=True)

    # Lifecycle
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    product = relationship("LicenseProduct", back_populates="tokens")
    instance = relationship("Instance", backref="license_tokens")

    def __repr__(self):
        return f"<LicenseToken(id={self.id}, used={self.used})>"


class LicenseSlot(Base):
    """Concurrency slot for controlled license installation rollout."""

    __tablename__ = "license_slots"

    id = Column(Integer, primary_key=True, index=True)
    slot_id = Column(String(50), unique=True, nullable=False, index=True)

    # Product association (concurrency is per-product)
    product_id = Column(Integer, ForeignKey("license_products.id", ondelete="CASCADE"), nullable=False, index=True)

    hostname = Column(String(255), nullable=True)
    ip_address = Column(String(50), nullable=True)
    acquired_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    released_at = Column(TIMESTAMP(timezone=True), nullable=True)
    result = Column(String(50), nullable=True)  # "success", "error", "expired"
    elapsed_seconds = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Relationships
    product = relationship("LicenseProduct", back_populates="slots")

    def __repr__(self):
        return f"<LicenseSlot(id={self.id}, slot_id={self.slot_id}, active={self.is_active})>"
