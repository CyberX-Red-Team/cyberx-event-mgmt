"""User/Invitee model."""
from sqlalchemy import Column, Integer, String, Boolean, BigInteger, TIMESTAMP, Index, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
import enum
from typing import Optional
from app.database import Base


class UserRole(str, enum.Enum):
    """User role enumeration."""
    ADMIN = "admin"  # Full access - event management, bulk emails, all invitees
    SPONSOR = "sponsor"  # Can manage invitees they sponsor
    INVITEE = "invitee"  # Invited to participate - becomes participant when confirmed


class User(Base):
    """
    User/Invitee model - replaces CyberX Master Invite SharePoint list.

    Users start as 'invitees' (role=INVITEE) and become 'participants'
    when they confirm participation for a specific event year.
    """

    __tablename__ = "users"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Migration tracking
    sharepoint_id = Column(String(50), unique=True, nullable=True)

    # Basic Information
    email = Column(String(255), nullable=False, index=True)  # Original email for sending
    email_normalized = Column(String(255), unique=True, nullable=False, index=True)  # Normalized for lookups
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    country = Column(String(100), nullable=False)

    # Role and Permissions
    role = Column(
        String(20),
        default=UserRole.INVITEE.value,
        nullable=False,
        index=True
    )

    # Sponsor relationship - who sponsored this invitee
    sponsor_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    sponsor = relationship("User", remote_side=[id], backref="sponsored_invitees", foreign_keys=[sponsor_id])

    # Legacy sponsor field (for migration from CSV)
    sponsor_email = Column(String(255), nullable=True)

    # Account Status
    # DEPRECATED: Use EventParticipation.status for event-specific tracking
    # This field will be removed once migration is complete
    confirmed = Column(String(20), default='UNKNOWN', nullable=False)  # YES/NO/UNKNOWN
    confirmed_at = Column(TIMESTAMP(timezone=True), nullable=True)  # When user confirmed participation
    decline_reason = Column(String(500), nullable=True)  # Optional reason for declining participation
    email_status = Column(String(50), default='GOOD', nullable=False)  # GOOD/BOUNCED/SPAM_REPORTED/UNSUBSCRIBED
    email_status_timestamp = Column(BigInteger, nullable=True)
    future_participation = Column(String(20), default='UNKNOWN')
    remove_permanently = Column(String(20), default='UNKNOWN')

    # Confirmation & Terms
    confirmation_code = Column(String(100), unique=True, nullable=True, index=True)
    confirmation_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    terms_accepted = Column(Boolean, default=False, nullable=False)
    terms_accepted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    terms_version = Column(String(50), nullable=True)

    # Credentials
    pandas_username = Column(String(255), unique=True, nullable=True, index=True)
    _pandas_password_encrypted = Column('pandas_password', String(500), nullable=True)  # Encrypted storage (Fernet)
    password_phonetic = Column(String(500), nullable=True)
    password_hash = Column(String(255), nullable=True)  # For web portal login (bcrypt)

    # Password Reset
    password_reset_token = Column(String(100), unique=True, nullable=True, index=True)
    password_reset_expires = Column(TIMESTAMP(timezone=True), nullable=True)

    # Discord Integration
    discord_username = Column(String(255), nullable=True)
    snowflake_id = Column(String(100), nullable=True)
    discord_invite_code = Column(String(50), nullable=True)
    discord_invite_sent = Column(TIMESTAMP(timezone=True), nullable=True)

    # Communication Tracking
    invite_id = Column(String(50), nullable=True)
    invite_sent = Column(TIMESTAMP(timezone=True), nullable=True)
    invite_reminder_sent = Column(TIMESTAMP(timezone=True), nullable=True)
    last_invite_sent = Column(TIMESTAMP(timezone=True), nullable=True)

    # Multi-stage Invitation Reminders
    reminder_1_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    reminder_2_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    reminder_3_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    password_email_sent = Column(TIMESTAMP(timezone=True), nullable=True)
    check_microsoft_email_sent = Column(TIMESTAMP(timezone=True), nullable=True)
    survey_email_sent = Column(TIMESTAMP(timezone=True), nullable=True)
    survey_response_timestamp = Column(TIMESTAMP(timezone=True), nullable=True)
    orientation_invite_email_sent = Column(TIMESTAMP(timezone=True), nullable=True)
    in_person_email_sent = Column(TIMESTAMP(timezone=True), nullable=True)

    # In-Person Attendance
    slated_in_person = Column(Boolean, default=False)
    confirmed_in_person = Column(Boolean, default=False)

    # System Fields
    azure_object_id = Column(String(100), nullable=True)
    pandas_groups = Column(String(500), nullable=True)
    is_admin = Column(Boolean, default=False)  # Legacy - use role instead
    is_active = Column(Boolean, default=True)

    # User Preferences
    theme_preference = Column(String(10), default='light', nullable=False)  # 'light' or 'dark'

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Event participation relationship
    event_participations = relationship(
        "EventParticipation",
        back_populates="user",
        foreign_keys="EventParticipation.user_id",
        cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index('idx_users_email', 'email'),
        Index('idx_users_pandas_username', 'pandas_username'),
        Index('idx_users_confirmed', 'confirmed'),
        Index('idx_users_email_status', 'email_status'),
        Index('idx_users_role', 'role'),
        Index('idx_users_sponsor_id', 'sponsor_id'),
    )

    # Helper properties for role checking
    @property
    def is_admin_role(self) -> bool:
        """Check if user has admin role."""
        return self.role == UserRole.ADMIN.value or self.is_admin

    @property
    def is_sponsor_role(self) -> bool:
        """Check if user has sponsor role (or higher)."""
        return self.role in (UserRole.ADMIN.value, UserRole.SPONSOR.value) or self.is_admin

    @property
    def is_invitee_role(self) -> bool:
        """Check if user has invitee role (regular user, not admin/sponsor)."""
        return self.role == UserRole.INVITEE.value and not self.is_admin

    @property
    def can_manage_invitees(self) -> bool:
        """Check if user can manage invitees."""
        return self.is_sponsor_role

    @property
    def can_send_bulk_emails(self) -> bool:
        """Check if user can send bulk emails to all invitees."""
        return self.is_admin_role

    @property
    def full_name(self) -> str:
        """Get user's full name."""
        return f"{self.first_name} {self.last_name}"

    # Participation tracking properties
    @property
    def years_invited(self) -> int:
        """Count how many years this user has been invited."""
        if not self.event_participations:
            return 0
        return len(self.event_participations)

    @property
    def years_participated(self) -> int:
        """Count how many years this user has confirmed participation."""
        if not self.event_participations:
            return 0
        from app.models.event import ParticipationStatus
        return sum(1 for p in self.event_participations if p.status == ParticipationStatus.CONFIRMED.value)

    @property
    def participation_rate(self) -> float:
        """Calculate participation rate as a percentage."""
        if self.years_invited == 0:
            return 0.0
        return (self.years_participated / self.years_invited) * 100

    @property
    def is_chronic_non_participant(self) -> bool:
        """
        Check if this user is a chronic non-participant.

        Criteria: Invited 3+ years and never participated.
        """
        return self.years_invited >= 3 and self.years_participated == 0

    @property
    def should_recommend_removal(self) -> bool:
        """
        Recommend removal from invitee list based on participation history.

        Criteria:
        - Invited 3+ years with 0 participations, OR
        - Invited 5+ years with participation rate < 20%
        """
        if self.years_invited >= 3 and self.years_participated == 0:
            return True
        if self.years_invited >= 5 and self.participation_rate < 20:
            return True
        return False

    # Event-specific confirmation helpers
    async def get_participation_for_event(self, event_id: int, session) -> Optional["EventParticipation"]:
        """
        Get EventParticipation record for a specific event.

        Args:
            event_id: The event ID to check
            session: Database session (AsyncSession)

        Returns:
            EventParticipation or None if not found
        """
        from sqlalchemy import select
        from app.models.event import EventParticipation

        result = await session.execute(
            select(EventParticipation).where(
                EventParticipation.user_id == self.id,
                EventParticipation.event_id == event_id
            )
        )
        return result.scalar_one_or_none()

    async def is_confirmed_for_event(self, event_id: int, session) -> bool:
        """
        Check if user is confirmed for a specific event.

        Args:
            event_id: The event ID to check
            session: Database session (AsyncSession)

        Returns:
            True if user has confirmed participation for this event
        """
        from app.models.event import ParticipationStatus

        participation = await self.get_participation_for_event(event_id, session)
        return participation and participation.status == ParticipationStatus.CONFIRMED.value

    async def get_current_event_participation(self, session) -> Optional["EventParticipation"]:
        """
        Get EventParticipation record for the current active event.

        Args:
            session: Database session (AsyncSession)

        Returns:
            EventParticipation for current event or None
        """
        from app.services.event_service import EventService

        event_service = EventService(session)
        event = await event_service.get_current_event()

        if not event:
            return None

        return await self.get_participation_for_event(event.id, session)

    def can_manage_invitee(self, invitee: "User") -> bool:
        """Check if this user can manage a specific invitee."""
        # Admins can manage anyone
        if self.is_admin_role:
            return True
        # Sponsors can manage invitees they sponsor
        if self.is_sponsor_role and invitee.sponsor_id == self.id:
            return True
        return False

    # Encrypted pandas_password property
    @hybrid_property
    def pandas_password(self) -> Optional[str]:
        """
        Get decrypted pandas password.

        Returns:
            Decrypted password or None
        """
        # Defensive check: if accessed at class level (not instance), return None
        # This prevents errors during SQLAlchemy inspection or class-level access
        from sqlalchemy.orm.attributes import InstrumentedAttribute
        if isinstance(self._pandas_password_encrypted, InstrumentedAttribute):
            return None

        if self._pandas_password_encrypted is None:
            return None

        try:
            from app.utils.encryption import decrypt_field
            return decrypt_field(self._pandas_password_encrypted)
        except Exception as e:
            # If decryption fails, assume it's plaintext (for backward compatibility during migration)
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to decrypt pandas_password for user {self.id}: {e}")
            # Return the raw value (likely plaintext from before encryption)
            return self._pandas_password_encrypted

    @pandas_password.setter
    def pandas_password(self, value: Optional[str]) -> None:
        """
        Set pandas password (automatically encrypts).

        Args:
            value: Plaintext password to encrypt and store
        """
        if value is None:
            self._pandas_password_encrypted = None
            return

        try:
            from app.utils.encryption import encrypt_field
            self._pandas_password_encrypted = encrypt_field(value)
        except Exception as e:
            # If encryption fails (e.g., encryptor not initialized during migration),
            # store as plaintext temporarily
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to encrypt pandas_password for user {self.id}: {e}")
            self._pandas_password_encrypted = value

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role}, name={self.full_name})>"


# Event listener to automatically set email_normalized from email
from sqlalchemy import event


@event.listens_for(User, 'before_insert')
@event.listens_for(User, 'before_update')
def normalize_user_email(mapper, connection, target):
    """
    Automatically normalize email when User is created or updated.

    This ensures email_normalized is always set correctly, even when
    tests or code create User objects without explicitly setting it.
    """
    if target.email and not target.email_normalized:
        from app.api.utils.validation import normalize_email
        target.email_normalized = normalize_email(target.email)
