"""Role model for dynamic roles and permissions."""
import enum
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, Index, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class BaseType(str, enum.Enum):
    """Base type for system-level access tiers."""
    ADMIN = "admin"
    SPONSOR = "sponsor"
    INVITEE = "invitee"


class Role(Base):
    """
    Dynamic role with permission management.

    Each role has a base_type (admin/sponsor/invitee) that preserves the
    three-tier access model for sidebar visibility, login redirects, and
    data scoping. Permissions are stored as a JSON array of permission
    strings. System roles (is_system=True) cannot be deleted.
    """
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    base_type = Column(String(20), nullable=False, index=True)
    permissions = Column(JSON, default=list, nullable=False)
    allowed_role_ids = Column(JSON, default=list, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    description = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    users = relationship("User", back_populates="role_obj", foreign_keys="User.role_id")

    __table_args__ = (
        Index('idx_roles_base_type', 'base_type'),
        Index('idx_roles_is_system', 'is_system'),
    )

    def __repr__(self):
        return f"<Role(id={self.id}, slug={self.slug}, base_type={self.base_type})>"
