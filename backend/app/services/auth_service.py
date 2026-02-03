"""Authentication service for session management."""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.session import Session
from app.utils.security import verify_password, generate_session_token


class AuthService:
    """Service for handling authentication and session management."""

    def __init__(self, session: AsyncSession, session_expiry_hours: int = 24):
        """
        Initialize auth service.

        Args:
            session: Database session
            session_expiry_hours: Hours until session expires (default 24)
        """
        self.session = session
        self.session_expiry_hours = session_expiry_hours

    async def authenticate_user(
        self,
        username: str,
        password: str
    ) -> Optional[User]:
        """
        Authenticate a user by username (email or pandas_username) and password.

        Args:
            username: Email or pandas_username
            password: Plain text password

        Returns:
            User object if authentication successful, None otherwise
        """
        # Try to find user by email or pandas_username
        result = await self.session.execute(
            select(User).where(
                (User.email == username) | (User.pandas_username == username)
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            return None

        # Check if user is active
        if not user.is_active:
            return None

        # Verify password hash exists
        if not user.password_hash:
            return None

        # Verify password
        if not verify_password(password, user.password_hash):
            return None

        return user

    async def create_session(
        self,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[str, datetime]:
        """
        Create a new session for a user.

        Args:
            user_id: User ID
            ip_address: Client IP address
            user_agent: Client user agent string

        Returns:
            Tuple of (session_token, expires_at)
        """
        # Generate secure token
        session_token = generate_session_token()

        # Calculate expiration
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self.session_expiry_hours)

        # Create session record
        session = Session(
            session_token=session_token,
            user_id=user_id,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            is_active=True
        )

        self.session.add(session)
        await self.session.commit()

        return session_token, expires_at

    async def validate_session(
        self,
        session_token: str
    ) -> Optional[User]:
        """
        Validate a session token and return the associated user.

        Args:
            session_token: Session token to validate

        Returns:
            User object if session is valid, None otherwise
        """
        # Query for active session
        result = await self.session.execute(
            select(Session).where(
                Session.session_token == session_token,
                Session.is_active == True
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            return None

        # Check if session has expired
        if session.expires_at < datetime.now(timezone.utc):
            # Mark session as inactive
            session.is_active = False
            await self.session.commit()
            return None

        # Get user with sponsor relationship loaded
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.sponsor))
            .where(User.id == session.user_id)
        )
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            return None

        return user

    async def invalidate_session(
        self,
        session_token: str
    ) -> bool:
        """
        Invalidate a session (logout).

        Args:
            session_token: Session token to invalidate

        Returns:
            True if session was invalidated, False if not found
        """
        result = await self.session.execute(
            select(Session).where(Session.session_token == session_token)
        )
        session = result.scalar_one_or_none()

        if not session:
            return False

        session.is_active = False
        await self.session.commit()

        return True

    async def invalidate_all_user_sessions(
        self,
        user_id: int
    ) -> int:
        """
        Invalidate all sessions for a user.

        Args:
            user_id: User ID

        Returns:
            Number of sessions invalidated
        """
        result = await self.session.execute(
            select(Session).where(
                Session.user_id == user_id,
                Session.is_active == True
            )
        )
        sessions = result.scalars().all()

        count = 0
        for session in sessions:
            session.is_active = False
            count += 1

        await self.session.commit()

        return count

    async def cleanup_expired_sessions(self) -> int:
        """
        Remove expired sessions from the database.

        Returns:
            Number of sessions removed
        """
        result = await self.session.execute(
            select(Session).where(Session.expires_at < datetime.now(timezone.utc))
        )
        sessions = result.scalars().all()

        count = 0
        for session in sessions:
            await self.session.delete(session)
            count += 1

        await self.session.commit()

        return count
