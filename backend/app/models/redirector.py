"""Redirector and StreamConfig ORM models for nginx stream proxy management."""
import enum
import uuid

from sqlalchemy import (
    Column, String, Boolean, Integer, TIMESTAMP, Text, ForeignKey, Index, JSON,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.database import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


class RedirectorStatus(str, enum.Enum):
    """Connectivity status of a redirector, updated by test-connection and deploy."""
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"


class StreamProtocol(str, enum.Enum):
    """Protocol for a stream config."""
    TCP = "tcp"
    UDP = "udp"
    DNS = "dns"   # UDP on port 53 + proxy_responses 1


class Redirector(Base):
    """
    A remote nginx redirector server managed via SSH.

    SSH private key and optional passphrase are stored Fernet-encrypted.
    The nginx_stream_dir must already be included in nginx.conf via:
        stream { include /etc/nginx/stream.d/*.conf; }
    This app only writes/deletes files inside stream_dir — never touches nginx.conf.
    """
    __tablename__ = "redirectors"
    __table_args__ = {'extend_existing': True}

    id = Column(String(36), primary_key=True, default=_new_uuid)
    name = Column(String(255), unique=True, nullable=False, index=True)
    current_ip = Column(String(45), nullable=False)
    ssh_port = Column(Integer, nullable=False, default=22)
    ssh_username = Column(String(255), nullable=False)

    # Fernet-encrypted at rest. Decrypted only in route handler scope, never logged.
    ssh_private_key = Column(Text, nullable=False)
    ssh_key_passphrase = Column(Text, nullable=True)   # nullable — passphrase is optional

    # Directory where individual .conf files are written (must exist on redirector)
    nginx_stream_dir = Column(String(500), nullable=False, default="/etc/nginx/stream.d")

    notes = Column(Text, nullable=True)

    # Owner — participants own the redirectors they create; admins see all
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    owner = relationship("User", foreign_keys=[owner_id])

    # Updated by test-connection and deploy operations
    status = Column(String(20), nullable=False, default=RedirectorStatus.UNKNOWN.value)
    last_deployed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_tested_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    stream_configs = relationship(
        "StreamConfig",
        back_populates="redirector",
        cascade="all, delete-orphan",
    )

    @property
    def stream_count(self) -> int:
        """Number of associated stream configs (requires eager load)."""
        return len(self.stream_configs) if self.stream_configs is not None else 0

    def __repr__(self):
        return f"<Redirector(id={self.id}, name={self.name!r}, status={self.status})>"


class StreamConfig(Base):
    """
    A single nginx stream server block, written to cyberx_<id>.conf on the redirector.

    Each enabled StreamConfig results in one file in the redirector's stream_dir.
    Disabled StreamConfigs have their file deleted from the remote server.
    """
    __tablename__ = "stream_configs"
    __table_args__ = (
        UniqueConstraint('redirector_id', 'listen_port', name='uq_stream_configs_redirector_port'),
        {'extend_existing': True},
    )

    id = Column(String(36), primary_key=True, default=_new_uuid)
    redirector_id = Column(
        String(36),
        ForeignKey("redirectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(255), nullable=False)
    protocol = Column(String(10), nullable=False, default=StreamProtocol.TCP.value)
    listen_port = Column(Integer, nullable=False)
    cs_ip = Column(String(255), nullable=False)   # CS teamserver IP or hostname
    cs_port = Column(Integer, nullable=False)

    # Access control: allow/deny by CIDR
    access_control_enabled = Column(Boolean, nullable=False, default=False)
    allowed_cidrs = Column(JSON, nullable=True)   # list[str], e.g. ["10.0.0.0/8", "1.2.3.4"]

    # SSL/TLS termination (TCP only; ignored for UDP/DNS)
    ssl_enabled = Column(Boolean, nullable=False, default=False)
    ssl_cert_path = Column(String(500), nullable=True)
    ssl_key_path = Column(String(500), nullable=True)
    ssl_protocols = Column(String(100), nullable=False, default="TLSv1.2 TLSv1.3")
    ssl_ciphers = Column(String(200), nullable=False, default="HIGH:!aNULL:!MD5")

    # If False, the .conf file is removed from the remote redirector
    enabled = Column(Boolean, nullable=False, default=True)
    # True when the config file has been deployed to the remote redirector
    deployed = Column(Boolean, nullable=False, default=False)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    redirector = relationship("Redirector", back_populates="stream_configs")

    @property
    def filename(self) -> str:
        """Remote filename for this stream config."""
        return f"cyberx_{self.id}.conf"

    def __repr__(self):
        return (
            f"<StreamConfig(id={self.id}, name={self.name!r}, "
            f"protocol={self.protocol}, port={self.listen_port})>"
        )
