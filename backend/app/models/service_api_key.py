"""Service API Key model for external integrations (bots, webhooks, etc.)."""
import secrets

from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, JSON
from sqlalchemy.sql import func

from app.database import Base


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"cxk_{secrets.token_urlsafe(32)}"


class ServiceAPIKey(Base):
    """API key for authenticating external services (Discord bot, etc.).

    Keys are stored as SHA-256 hashes. The plaintext is shown once at creation
    and never stored.
    """

    __tablename__ = "service_api_keys"

    id = Column(Integer, primary_key=True, index=True)

    # Human-readable label (e.g., "Discord Bot - Production")
    name = Column(String(255), nullable=False)

    # SHA-256 hash of the API key (prefix stored separately for identification)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(12), nullable=False)  # e.g., "cxk_Ab3x..."

    # Scopes control what the key can do (list of strings)
    # e.g., ["bot.verify", "bot.lookup", "bot.update"]
    scopes = Column(JSON, nullable=False, default=list)

    # Active toggle — allows disabling without deleting
    is_active = Column(Boolean, default=True, nullable=False)

    # Usage tracking
    last_used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_used_ip = Column(String(45), nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
