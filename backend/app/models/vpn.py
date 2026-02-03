"""VPN Credential model."""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, Text, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class VPNCredential(Base):
    """VPN Credential model - replaces VPN Configs V2 SharePoint list."""

    __tablename__ = "vpn_credentials"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Migration tracking
    sharepoint_id = Column(String(50), unique=True, nullable=True)

    # IP Addresses (comma-separated: IPv4, IPv6 link-local, IPv6 global)
    interface_ip = Column(Text, nullable=False)  # Full string: "10.20.200.149,fd00:a:14:c8:95::95,..."
    ipv4_address = Column(String(50), nullable=True)    # Extracted: 10.20.200.149
    ipv6_local = Column(String(100), nullable=True)     # Extracted: fd00:a:14:c8:95::95
    ipv6_global = Column(String(100), nullable=True)    # Extracted: fd00:a:14:c8:95:ffff:a14:c895

    # WireGuard Keys (base64 encoded)
    private_key = Column(Text, nullable=False)
    preshared_key = Column(Text, nullable=True)  # Optional: provides post-quantum security

    # VPN Configuration
    endpoint = Column(String(100), nullable=False)  # "216.208.235.11:51020"
    key_type = Column(String(20), nullable=False)   # cyber/kinetic

    # Assignment
    assigned_to_username = Column(String(255), nullable=True)
    assigned_to_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Tracking
    file_hash = Column(String(64), nullable=True)
    file_id = Column(String(50), nullable=True)
    run_id = Column(String(100), nullable=True)
    request_batch_id = Column(String(50), nullable=True)  # Tracks which request batch this VPN was assigned in

    # Status
    is_available = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    assigned_to_user = relationship("User", backref="vpn_credentials", foreign_keys=[assigned_to_user_id])

    # Indexes
    __table_args__ = (
        Index('idx_vpn_assigned_to_user_id', 'assigned_to_user_id'),
        Index('idx_vpn_is_available', 'is_available'),
        Index('idx_vpn_key_type', 'key_type'),
        Index('idx_vpn_assigned_to_username', 'assigned_to_username'),
        Index('idx_vpn_request_batch_id', 'request_batch_id'),
    )

    def __repr__(self):
        return f"<VPNCredential(id={self.id}, ip={self.ipv4_address}, type={self.key_type}, available={self.is_available})>"
