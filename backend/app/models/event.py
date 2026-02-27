"""Event and participation tracking models."""
import enum
import re
from sqlalchemy import (
    Column, Integer, String, Boolean, TIMESTAMP, Date,
    ForeignKey, Index, Text, UniqueConstraint
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


def generate_slug(name: str) -> str:
    """
    Generate a URL-friendly slug from an event name.

    Examples:
        "CyberX Red Team Exercise 2026" -> "cyberx-red-team-exercise-2026"
        "Spring Event 2026!" -> "spring-event-2026"
    """
    # Convert to lowercase
    slug = name.lower()
    # Remove special characters (keep alphanumeric, spaces, and hyphens)
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    # Replace multiple spaces/hyphens with single hyphen
    slug = re.sub(r'[\s-]+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    return slug


class ParticipationStatus(str, enum.Enum):
    """Status of an invitee's participation for an event."""
    INVITED = "invited"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    NO_RESPONSE = "no_response"


class Event(Base):
    """
    Represents an annual CyberX event.

    Manages event lifecycle including invitation activation, registration,
    and participation tracking.
    """
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)

    # Event identification
    year = Column(Integer, nullable=False, index=True)  # No longer unique - allows multiple events per year
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)  # URL-friendly unique identifier

    # Event dates
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    event_time = Column(String(255), nullable=True)  # e.g., "Doors open 18:00 UTC"
    event_location = Column(String(255), nullable=True)  # e.g., "Austin, TX"

    # Registration period
    registration_opens = Column(TIMESTAMP(timezone=True), nullable=True)
    registration_closes = Column(TIMESTAMP(timezone=True), nullable=True)
    registration_open = Column(
        Boolean,
        default=False,
        nullable=False
    )  # Quick toggle for registration

    # Terms of agreement
    terms_version = Column(String(50), nullable=True)
    terms_content = Column(Text, nullable=True)
    terms_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Status
    is_active = Column(Boolean, default=False, index=True)
    is_archived = Column(Boolean, default=False)
    # Controls when users can request VPNs
    vpn_available = Column(Boolean, default=False, nullable=False)
    # Allows sponsors to test VPN and Keycloak sync
    test_mode = Column(Boolean, default=False, nullable=False)

    # Configuration
    max_participants = Column(Integer, nullable=True)
    confirmation_expires_days = Column(Integer, default=30)

    # SSH Keys (for participant instance access)
    ssh_public_key = Column(Text, nullable=True)
    ssh_private_key = Column(Text, nullable=True)

    # Discord integration
    discord_channel_id = Column(String(100), nullable=True)  # Discord channel for invite generation

    # Timestamps
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Relationships
    participations = relationship(
        "EventParticipation",
        back_populates="event",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<Event(id={self.id}, slug={self.slug}, year={self.year}, "
            f"name={self.name}, is_active={self.is_active})>"
        )


class EventParticipation(Base):
    """
    Tracks an invitee's participation status for a specific event year.

    This allows tracking:
    - When someone was invited for each year
    - Whether they confirmed, declined, or didn't respond
    - Historical participation patterns
    """
    __tablename__ = "event_participations"

    id = Column(Integer, primary_key=True, index=True)

    # References
    user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    event_id = Column(
        Integer,
        ForeignKey('events.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    # Invitation tracking
    invited_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    invited_by_user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )

    # Response tracking
    status = Column(
        String(20),
        default=ParticipationStatus.INVITED.value,
        nullable=False,
        index=True
    )
    responded_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Terms acceptance (for confirmed participants)
    terms_accepted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    terms_version_accepted = Column(String(50), nullable=True)

    # Confirmation/Decline tracking
    confirmed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    declined_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Notes
    notes = Column(Text, nullable=True)
    declined_reason = Column(Text, nullable=True)

    # Discord invite
    discord_invite_code = Column(String(50), nullable=True)
    discord_invite_generated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    discord_invite_used_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # Relationships
    user = relationship(
        "User",
        back_populates="event_participations",
        foreign_keys=[user_id]
    )
    event = relationship("Event", back_populates="participations")
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])

    # Constraints
    __table_args__ = (
        UniqueConstraint('user_id', 'event_id', name='uq_user_event'),
        Index('idx_participation_user_event', 'user_id', 'event_id'),
        Index('idx_participation_status', 'status'),
    )

    @property
    def is_confirmed(self) -> bool:
        """Check if participation is confirmed."""
        return self.status == ParticipationStatus.CONFIRMED.value

    @property
    def is_pending(self) -> bool:
        """Check if still waiting for response."""
        return self.status == ParticipationStatus.INVITED.value

    def __repr__(self):
        return (
            f"<EventParticipation(user_id={self.user_id}, "
            f"event_id={self.event_id}, status={self.status})>"
        )
