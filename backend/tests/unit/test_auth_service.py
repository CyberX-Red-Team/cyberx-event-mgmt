"""
Unit tests for AuthService.

Tests authentication, session creation, validation, invalidation,
and session cleanup operations.
"""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import AuthService
from app.models.user import User, UserRole
from app.models.session import Session
from app.utils.security import hash_password


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuthServiceAuthentication:
    """Test user authentication operations."""

    async def test_authenticate_with_email(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test authenticating user with email."""
        service = AuthService(db_session)

        user = await service.authenticate_user(
            username=admin_user.email,
            password="admin123"  # Default password from fixture
        )

        assert user is not None
        assert user.id == admin_user.id
        assert user.email == admin_user.email

    async def test_authenticate_with_pandas_username(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test authenticating user with pandas_username."""
        service = AuthService(db_session)

        user = await service.authenticate_user(
            username=admin_user.pandas_username,
            password="admin123"
        )

        assert user is not None
        assert user.id == admin_user.id

    async def test_authenticate_wrong_password(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test authentication fails with wrong password."""
        service = AuthService(db_session)

        user = await service.authenticate_user(
            username=admin_user.email,
            password="wrongpassword"
        )

        assert user is None

    async def test_authenticate_nonexistent_user(self, db_session: AsyncSession):
        """Test authentication fails for non-existent user."""
        service = AuthService(db_session)

        user = await service.authenticate_user(
            username="nonexistent@test.com",
            password="password"
        )

        assert user is None

    async def test_authenticate_inactive_user(self, db_session: AsyncSession):
        """Test authentication fails for inactive user."""
        service = AuthService(db_session)

        # Create inactive user
        inactive_user = User(
            email="inactive@test.com",
            first_name="Inactive",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value,
            is_active=False,
            password_hash=hash_password("password123")
        )
        db_session.add(inactive_user)
        await db_session.commit()

        user = await service.authenticate_user(
            username="inactive@test.com",
            password="password123"
        )

        assert user is None

    async def test_authenticate_user_without_password_hash(
        self, db_session: AsyncSession
    ):
        """Test authentication fails for user without password_hash."""
        service = AuthService(db_session)

        # Create user without password_hash
        no_password_user = User(
            email="nopassword@test.com",
            first_name="No",
            last_name="Password",
            country="USA",
            role=UserRole.INVITEE.value,
            is_active=True,
            password_hash=None
        )
        db_session.add(no_password_user)
        await db_session.commit()

        user = await service.authenticate_user(
            username="nopassword@test.com",
            password="anypassword"
        )

        assert user is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuthServiceSessionCreation:
    """Test session creation operations."""

    async def test_create_session_basic(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test creating a basic session."""
        service = AuthService(db_session)

        token, expires_at = await service.create_session(admin_user.id)

        assert token is not None
        assert len(token) > 20  # Should be secure token
        assert isinstance(expires_at, datetime)
        assert expires_at > datetime.now(timezone.utc)

    async def test_create_session_with_metadata(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test creating session with IP and user agent."""
        service = AuthService(db_session)

        token, expires_at = await service.create_session(
            user_id=admin_user.id,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0"
        )

        assert token is not None

        # Verify session was stored with metadata
        from sqlalchemy import select
        result = await db_session.execute(
            select(Session).where(Session.session_token == token)
        )
        session = result.scalar_one_or_none()

        assert session is not None
        assert session.ip_address == "192.168.1.1"
        assert session.user_agent == "Mozilla/5.0"
        assert session.is_active is True

    async def test_create_session_expiration(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test session expiration is set correctly."""
        service = AuthService(db_session, session_expiry_hours=48)

        token, expires_at = await service.create_session(admin_user.id)

        # Check expiration is approximately 48 hours from now
        expected_expiry = datetime.now(timezone.utc) + timedelta(hours=48)
        time_diff = abs((expires_at - expected_expiry).total_seconds())
        assert time_diff < 5  # Within 5 seconds

    async def test_create_multiple_sessions(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test creating multiple sessions generates unique tokens."""
        service = AuthService(db_session)

        token1, _ = await service.create_session(admin_user.id)
        token2, _ = await service.create_session(admin_user.id)

        assert token1 != token2


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuthServiceSessionValidation:
    """Test session validation operations."""

    async def test_validate_valid_session(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test validating a valid session."""
        service = AuthService(db_session)

        # Create session
        token, _ = await service.create_session(admin_user.id)

        # Validate session
        user = await service.validate_session(token)

        assert user is not None
        assert user.id == admin_user.id

    async def test_validate_invalid_token(self, db_session: AsyncSession):
        """Test validating non-existent token returns None."""
        service = AuthService(db_session)

        user = await service.validate_session("invalid-token-12345")

        assert user is None

    async def test_validate_expired_session(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test validating expired session returns None and marks inactive."""
        service = AuthService(db_session)

        # Create expired session
        token, _ = await service.create_session(admin_user.id)

        # Manually expire the session
        from sqlalchemy import select
        result = await db_session.execute(
            select(Session).where(Session.session_token == token)
        )
        session = result.scalar_one()
        session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db_session.commit()

        # Validate should return None
        user = await service.validate_session(token)
        assert user is None

        # Session should be marked inactive
        await db_session.refresh(session)
        assert session.is_active is False

    async def test_validate_inactive_session(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test validating inactive session returns None."""
        service = AuthService(db_session)

        # Create and invalidate session
        token, _ = await service.create_session(admin_user.id)
        await service.invalidate_session(token)

        # Validate should return None
        user = await service.validate_session(token)
        assert user is None

    async def test_validate_session_with_inactive_user(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test validating session for inactive user returns None."""
        service = AuthService(db_session)

        # Create session
        token, _ = await service.create_session(admin_user.id)

        # Deactivate user
        admin_user.is_active = False
        await db_session.commit()

        # Validate should return None
        user = await service.validate_session(token)
        assert user is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuthServiceSessionInvalidation:
    """Test session invalidation operations."""

    async def test_invalidate_session(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test invalidating a single session."""
        service = AuthService(db_session)

        # Create session
        token, _ = await service.create_session(admin_user.id)

        # Invalidate
        success = await service.invalidate_session(token)
        assert success is True

        # Verify session is inactive
        user = await service.validate_session(token)
        assert user is None

    async def test_invalidate_nonexistent_session(self, db_session: AsyncSession):
        """Test invalidating non-existent session returns False."""
        service = AuthService(db_session)

        success = await service.invalidate_session("nonexistent-token")
        assert success is False

    async def test_invalidate_all_user_sessions(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test invalidating all sessions for a user."""
        service = AuthService(db_session)

        # Create multiple sessions
        token1, _ = await service.create_session(admin_user.id)
        token2, _ = await service.create_session(admin_user.id)
        token3, _ = await service.create_session(admin_user.id)

        # Invalidate all
        count = await service.invalidate_all_user_sessions(admin_user.id)
        assert count == 3

        # Verify all sessions are invalid
        assert await service.validate_session(token1) is None
        assert await service.validate_session(token2) is None
        assert await service.validate_session(token3) is None

    async def test_invalidate_all_user_sessions_no_sessions(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test invalidating all sessions when user has none."""
        service = AuthService(db_session)

        count = await service.invalidate_all_user_sessions(admin_user.id)
        assert count == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuthServiceSessionCleanup:
    """Test session cleanup operations."""

    async def test_cleanup_expired_sessions(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test cleaning up expired sessions."""
        service = AuthService(db_session)

        # Create expired sessions
        token1, _ = await service.create_session(admin_user.id)
        token2, _ = await service.create_session(admin_user.id)

        # Manually expire them
        from sqlalchemy import select
        result = await db_session.execute(
            select(Session).where(
                Session.session_token.in_([token1, token2])
            )
        )
        sessions = result.scalars().all()
        for session in sessions:
            session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db_session.commit()

        # Cleanup
        count = await service.cleanup_expired_sessions()
        assert count == 2

        # Verify sessions are deleted
        result = await db_session.execute(
            select(Session).where(
                Session.session_token.in_([token1, token2])
            )
        )
        remaining = result.scalars().all()
        assert len(remaining) == 0

    async def test_cleanup_preserves_active_sessions(
        self, db_session: AsyncSession, admin_user: User
    ):
        """Test cleanup doesn't remove active sessions."""
        service = AuthService(db_session)

        # Create active session
        token, _ = await service.create_session(admin_user.id)

        # Cleanup
        count = await service.cleanup_expired_sessions()
        assert count == 0

        # Verify session still exists and is valid
        user = await service.validate_session(token)
        assert user is not None

    async def test_cleanup_no_expired_sessions(self, db_session: AsyncSession):
        """Test cleanup when no expired sessions exist."""
        service = AuthService(db_session)

        count = await service.cleanup_expired_sessions()
        assert count == 0
