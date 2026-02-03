"""
Unit tests for ParticipantService.

Tests participant management operations including create, update, delete,
list, and business logic.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.participant_service import ParticipantService
from app.models.user import User, UserRole
from app.models.event import Event


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceCreate:
    """Test participant creation operations."""

    async def test_create_participant_basic(self, db_session: AsyncSession):
        """Test creating a basic participant."""
        service = ParticipantService(db_session)

        user = await service.create_participant(
            email="newuser@test.com",
            first_name="New",
            last_name="User",
            country="USA"
        )

        assert user.id is not None
        assert user.email == "newuser@test.com"
        assert user.first_name == "New"
        assert user.last_name == "User"
        assert user.country == "USA"
        assert user.role == UserRole.INVITEE.value
        assert user.is_active is True
        assert user.confirmed == "UNKNOWN"

    async def test_create_participant_without_credentials(self, db_session: AsyncSession):
        """Test that new invitees don't get credentials immediately."""
        service = ParticipantService(db_session)

        user = await service.create_participant(
            email="invitee@test.com",
            first_name="Test",
            last_name="Invitee",
            country="USA",
            confirmed="UNKNOWN"
        )

        # New invitees should NOT have credentials yet
        assert user.pandas_username is None
        assert user.pandas_password is None
        assert user.password_hash is None

    async def test_create_confirmed_participant_gets_credentials(
        self, db_session: AsyncSession
    ):
        """Test that confirmed participants get credentials."""
        service = ParticipantService(db_session)

        user = await service.create_participant(
            email="confirmed@test.com",
            first_name="Confirmed",
            last_name="User",
            country="USA",
            confirmed="YES"
        )

        # Confirmed users should get credentials
        assert user.pandas_username is not None
        assert user.pandas_password is not None
        assert user.password_hash is not None
        assert user.password_phonetic is not None

    async def test_create_admin_user(self, db_session: AsyncSession):
        """Test creating an admin user."""
        service = ParticipantService(db_session)

        admin = await service.create_participant(
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        assert admin.role == UserRole.ADMIN.value
        assert admin.is_admin is True
        # Admins get immediate credentials
        assert admin.pandas_username is not None
        assert admin.pandas_password is not None

    async def test_create_sponsor_user(self, db_session: AsyncSession):
        """Test creating a sponsor user."""
        service = ParticipantService(db_session)

        sponsor = await service.create_participant(
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )

        assert sponsor.role == UserRole.SPONSOR.value
        # Sponsors get immediate credentials
        assert sponsor.pandas_username is not None
        assert sponsor.pandas_password is not None

    async def test_create_participant_with_sponsor(
        self, db_session: AsyncSession, sponsor_user: User
    ):
        """Test creating a participant with sponsor relationship."""
        service = ParticipantService(db_session)

        user = await service.create_participant(
            email="sponsored@test.com",
            first_name="Sponsored",
            last_name="User",
            country="USA",
            sponsor_id=sponsor_user.id
        )

        assert user.sponsor_id == sponsor_user.id
        assert user.sponsor == sponsor_user

    async def test_create_participant_with_custom_credentials(
        self, db_session: AsyncSession
    ):
        """Test creating participant with pre-specified credentials."""
        service = ParticipantService(db_session)

        user = await service.create_participant(
            email="custom@test.com",
            first_name="Custom",
            last_name="User",
            country="USA",
            pandas_username="customuser",
            pandas_password="CustomPass123!"
        )

        assert user.pandas_username == "customuser"
        # Password should be encrypted
        assert user.pandas_password == "CustomPass123!"
        # Should have password hash
        assert user.password_hash is not None


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceRetrieve:
    """Test participant retrieval operations."""

    async def test_get_participant_by_id(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test retrieving participant by ID."""
        service = ParticipantService(db_session)

        user = await service.get_participant(invitee_user.id)

        assert user is not None
        assert user.id == invitee_user.id
        assert user.email == invitee_user.email

    async def test_get_nonexistent_participant(self, db_session: AsyncSession):
        """Test retrieving non-existent participant returns None."""
        service = ParticipantService(db_session)

        user = await service.get_participant(99999)

        assert user is None

    async def test_get_participant_by_email(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test retrieving participant by email."""
        service = ParticipantService(db_session)

        user = await service.get_participant_by_email(invitee_user.email)

        assert user is not None
        assert user.id == invitee_user.id
        assert user.email == invitee_user.email

    async def test_get_nonexistent_email(self, db_session: AsyncSession):
        """Test retrieving non-existent email returns None."""
        service = ParticipantService(db_session)

        user = await service.get_participant_by_email("nonexistent@test.com")

        assert user is None

    async def test_list_participants(
        self,
        db_session: AsyncSession,
        admin_user: User,
        sponsor_user: User,
        invitee_user: User,
    ):
        """Test listing all participants."""
        service = ParticipantService(db_session)

        users, total = await service.list_participants(page=1, page_size=50)

        assert total >= 3  # At least our fixtures
        assert len(users) >= 3
        user_ids = [u.id for u in users]
        assert admin_user.id in user_ids
        assert sponsor_user.id in user_ids
        assert invitee_user.id in user_ids

    async def test_list_participants_with_search(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test listing participants with search filter."""
        service = ParticipantService(db_session)

        users, total = await service.list_participants(
            search=invitee_user.email, page=1, page_size=50
        )

        assert total >= 1
        assert any(u.id == invitee_user.id for u in users)

    async def test_list_participants_pagination(self, db_session: AsyncSession):
        """Test participant list pagination."""
        service = ParticipantService(db_session)

        # Create multiple users
        for i in range(5):
            await service.create_participant(
                email=f"user{i}@test.com",
                first_name=f"User{i}",
                last_name="Test",
                country="USA",
            )

        # Get first page (2 per page)
        users_page1, total = await service.list_participants(page=1, page_size=2)
        assert len(users_page1) == 2
        assert total >= 5

        # Get second page
        users_page2, total = await service.list_participants(page=2, page_size=2)
        assert len(users_page2) == 2

        # Pages should have different users
        page1_ids = {u.id for u in users_page1}
        page2_ids = {u.id for u in users_page2}
        assert len(page1_ids & page2_ids) == 0  # No overlap


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceUpdate:
    """Test participant update operations."""

    async def test_update_participant_email(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test updating participant email."""
        service = ParticipantService(db_session)

        updated = await service.update_participant(
            invitee_user.id, email="newemail@test.com"
        )

        assert updated is not None
        assert updated.email == "newemail@test.com"

    async def test_update_participant_name(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test updating participant name."""
        service = ParticipantService(db_session)

        updated = await service.update_participant(
            invitee_user.id, first_name="NewFirst", last_name="NewLast"
        )

        assert updated.first_name == "NewFirst"
        assert updated.last_name == "NewLast"

    async def test_update_participant_confirmed_status(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test updating participant confirmed status."""
        service = ParticipantService(db_session)

        # Initially UNKNOWN
        assert invitee_user.confirmed == "UNKNOWN"
        assert invitee_user.confirmed_at is None

        # Update to YES
        updated = await service.update_participant(
            invitee_user.id, confirmed="YES"
        )

        assert updated.confirmed == "YES"
        assert updated.confirmed_at is not None
        assert isinstance(updated.confirmed_at, datetime)

    async def test_update_nonexistent_participant(self, db_session: AsyncSession):
        """Test updating non-existent participant returns None."""
        service = ParticipantService(db_session)

        result = await service.update_participant(99999, first_name="Test")

        assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceDelete:
    """Test participant deletion operations."""

    async def test_delete_participant(self, db_session: AsyncSession):
        """Test deleting a participant."""
        service = ParticipantService(db_session)

        # Create user
        user = await service.create_participant(
            email="delete@test.com",
            first_name="Delete",
            last_name="Me",
            country="USA",
        )
        user_id = user.id

        # Delete
        success = await service.delete_participant(user_id)
        assert success is True

        # Verify deleted
        deleted = await service.get_participant(user_id)
        assert deleted is None

    async def test_delete_nonexistent_participant(self, db_session: AsyncSession):
        """Test deleting non-existent participant returns False."""
        service = ParticipantService(db_session)

        success = await service.delete_participant(99999)

        assert success is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServicePasswordManagement:
    """Test password reset and management."""

    async def test_reset_password_generates_new(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test resetting password generates new password."""
        service = ParticipantService(db_session)

        success, new_password = await service.reset_password(invitee_user.id)

        assert success is True
        assert new_password is not None
        assert len(new_password) >= 12  # Should be reasonably long
        # Password should be encrypted in database
        assert invitee_user.pandas_password == new_password

    async def test_reset_password_with_custom(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test resetting password with custom password."""
        service = ParticipantService(db_session)

        custom_password = "CustomPassword123!"
        success, new_password = await service.reset_password(
            invitee_user.id, new_password=custom_password
        )

        assert success is True
        assert new_password == custom_password

    async def test_reset_password_nonexistent_user(self, db_session: AsyncSession):
        """Test resetting password for non-existent user."""
        service = ParticipantService(db_session)

        success, password = await service.reset_password(99999)

        assert success is False
        assert password == ""
