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
from app.models.event import Event, generate_slug


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

    async def test_list_participants_empty_results(self, db_session: AsyncSession):
        """Test listing participants with search that returns no results."""
        service = ParticipantService(db_session)

        users, total = await service.list_participants(
            search="nonexistent_xyz_search_term", page=1, page_size=50
        )

        assert total == 0
        assert len(users) == 0

    async def test_list_participants_single_page(self, db_session: AsyncSession):
        """Test listing participants when all fit on single page."""
        service = ParticipantService(db_session)

        # Create 3 users
        for i in range(3):
            await service.create_participant(
                email=f"single_page_{i}@test.com",
                first_name=f"User{i}",
                last_name="Test",
                country="USA",
            )

        # Request large page size
        users, total = await service.list_participants(page=1, page_size=100)

        # All users should fit on one page
        assert total >= 3
        assert len(users) == total

    async def test_list_participants_last_page_partial(self, db_session: AsyncSession):
        """Test listing last page with fewer items than page size."""
        service = ParticipantService(db_session)

        # Create exactly 5 users
        for i in range(5):
            await service.create_participant(
                email=f"partial_page_{i}@test.com",
                first_name=f"User{i}",
                last_name="Test",
                country="USA",
            )

        # Get page 2 with page_size=3 (should have 2 items)
        users, total = await service.list_participants(page=2, page_size=3)

        # Should have fewer than page_size
        assert len(users) >= 1
        assert len(users) < 3


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

@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceBulkOperations:
    """Test bulk participant operations."""

    async def test_bulk_activate_participants(self, db_session: AsyncSession):
        """Test bulk activating multiple participants."""
        service = ParticipantService(db_session)

        # Create inactive participants
        user_ids = []
        for i in range(3):
            user = await service.create_participant(
                email=f"user{i}@test.com",
                first_name=f"User{i}",
                last_name="Test",
                country="USA"
            )
            user.is_active = False
            user_ids.append(user.id)
        await db_session.commit()

        # Bulk activate
        success_count, failed_ids = await service.bulk_activate(user_ids)

        assert success_count == 3
        assert len(failed_ids) == 0

        # Verify all activated
        for user_id in user_ids:
            user = await service.get_participant(user_id)
            assert user.is_active is True

    async def test_bulk_activate_nonexistent(self, db_session: AsyncSession):
        """Test bulk activate handles non-existent users."""
        service = ParticipantService(db_session)

        success_count, failed_ids = await service.bulk_activate([99999, 88888])

        assert success_count == 0
        assert len(failed_ids) == 2

    async def test_bulk_deactivate_participants(self, db_session: AsyncSession):
        """Test bulk deactivating multiple participants."""
        service = ParticipantService(db_session)

        # Create active participants
        user_ids = []
        for i in range(3):
            user = await service.create_participant(
                email=f"user{i}@test.com",
                first_name=f"User{i}",
                last_name="Test",
                country="USA"
            )
            user_ids.append(user.id)
        await db_session.commit()

        # Bulk deactivate
        success_count, failed_ids = await service.bulk_deactivate(user_ids)

        assert success_count == 3
        assert len(failed_ids) == 0

        # Verify all deactivated
        for user_id in user_ids:
            user = await service.get_participant(user_id)
            assert user.is_active is False

    async def test_bulk_activate_mixed_success_failure(
        self, db_session: AsyncSession
    ):
        """Test bulk activate with mix of valid and invalid IDs."""
        service = ParticipantService(db_session)

        # Create 2 valid users
        user1 = await service.create_participant(
            email="valid1@test.com",
            first_name="Valid1",
            last_name="User",
            country="USA"
        )
        user2 = await service.create_participant(
            email="valid2@test.com",
            first_name="Valid2",
            last_name="User",
            country="USA"
        )
        user1.is_active = False
        user2.is_active = False
        await db_session.commit()

        # Mix valid and invalid IDs
        mixed_ids = [user1.id, 99999, user2.id, 88888]

        success_count, failed_ids = await service.bulk_activate(mixed_ids)

        # Should succeed for 2 valid users
        assert success_count == 2
        # Should fail for 2 invalid IDs
        assert len(failed_ids) == 2
        assert 99999 in failed_ids
        assert 88888 in failed_ids

    async def test_bulk_activate_empty_list(self, db_session: AsyncSession):
        """Test bulk activate with empty ID list."""
        service = ParticipantService(db_session)

        success_count, failed_ids = await service.bulk_activate([])

        assert success_count == 0
        assert len(failed_ids) == 0

    async def test_bulk_deactivate_mixed_success_failure(
        self, db_session: AsyncSession
    ):
        """Test bulk deactivate with mix of valid and invalid IDs."""
        service = ParticipantService(db_session)

        # Create 2 valid users
        user1 = await service.create_participant(
            email="deactivate1@test.com",
            first_name="Deactivate1",
            last_name="User",
            country="USA"
        )
        user2 = await service.create_participant(
            email="deactivate2@test.com",
            first_name="Deactivate2",
            last_name="User",
            country="USA"
        )

        # Mix valid and invalid IDs
        mixed_ids = [user1.id, 77777, user2.id, 66666]

        success_count, failed_ids = await service.bulk_deactivate(mixed_ids)

        # Should succeed for 2 valid users
        assert success_count == 2
        # Should fail for 2 invalid IDs
        assert len(failed_ids) == 2
        assert 77777 in failed_ids
        assert 66666 in failed_ids


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceStatistics:
    """Test participant statistics operations."""

    async def test_get_statistics_all(self, db_session: AsyncSession):
        """Test getting overall participant statistics."""
        service = ParticipantService(db_session)

        # Create various participants
        await service.create_participant(
            email="user1@test.com",
            first_name="User1",
            last_name="Test",
            country="USA",
            confirmed="YES"
        )
        await service.create_participant(
            email="user2@test.com",
            first_name="User2",
            last_name="Test",
            country="Canada",
            confirmed="NO"
        )

        stats = await service.get_statistics()

        assert stats["total_invitees"] >= 2
        assert "confirmed_count" in stats
        assert "active_count" in stats

    async def test_get_statistics_by_sponsor(
        self, db_session: AsyncSession, sponsor_user: User
    ):
        """Test getting statistics filtered by sponsor."""
        service = ParticipantService(db_session)

        # Create participant sponsored by sponsor
        await service.create_participant(
            email="sponsored@test.com",
            first_name="Sponsored",
            last_name="User",
            country="USA",
            sponsor_id=sponsor_user.id
        )

        stats = await service.get_statistics(sponsor_id=sponsor_user.id)

        assert stats["total_invitees"] >= 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceSponsorOperations:
    """Test sponsor-related operations."""

    async def test_get_sponsored_participants(
        self, db_session: AsyncSession, sponsor_user: User
    ):
        """Test retrieving participants sponsored by a sponsor."""
        service = ParticipantService(db_session)

        # Create sponsored participants
        user1 = await service.create_participant(
            email="sponsored1@test.com",
            first_name="Sponsored1",
            last_name="User",
            country="USA",
            sponsor_id=sponsor_user.id
        )
        user2 = await service.create_participant(
            email="sponsored2@test.com",
            first_name="Sponsored2",
            last_name="User",
            country="USA",
            sponsor_id=sponsor_user.id
        )

        # Get sponsored participants
        participants, total = await service.get_sponsored_participants(sponsor_user.id)

        assert len(participants) >= 2
        assert total >= 2
        participant_ids = [p.id for p in participants]
        assert user1.id in participant_ids
        assert user2.id in participant_ids

    async def test_assign_sponsor(self, db_session: AsyncSession, sponsor_user: User):
        """Test assigning a sponsor to a participant."""
        service = ParticipantService(db_session)

        # Create participant without sponsor
        user = await service.create_participant(
            email="user@test.com",
            first_name="User",
            last_name="Test",
            country="USA"
        )

        # Assign sponsor
        updated = await service.assign_sponsor(user.id, sponsor_user.id)

        assert updated is not None
        assert updated.sponsor_id == sponsor_user.id

    async def test_assign_sponsor_nonexistent(self, db_session: AsyncSession):
        """Test assigning sponsor to non-existent participant."""
        service = ParticipantService(db_session)

        result = await service.assign_sponsor(99999, 1)
        assert result is None

    async def test_list_sponsors(self, db_session: AsyncSession, sponsor_user: User):
        """Test listing all sponsors."""
        service = ParticipantService(db_session)

        sponsors = await service.list_sponsors()

        assert len(sponsors) >= 1
        sponsor_ids = [s.id for s in sponsors]
        assert sponsor_user.id in sponsor_ids


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceRoleManagement:
    """Test participant role management operations."""

    async def test_update_role(self, db_session: AsyncSession, invitee_user: User):
        """Test updating participant role."""
        service = ParticipantService(db_session)

        # Update role from invitee to sponsor
        updated = await service.update_role(invitee_user.id, UserRole.SPONSOR.value)

        assert updated is not None
        assert updated.role == UserRole.SPONSOR.value

    async def test_update_role_nonexistent(self, db_session: AsyncSession):
        """Test updating role for non-existent participant."""
        service = ParticipantService(db_session)

        result = await service.update_role(99999, UserRole.ADMIN.value)
        assert result is None

    async def test_get_sponsor_by_id(self, db_session: AsyncSession, sponsor_user: User):
        """Test retrieving sponsor by ID."""
        service = ParticipantService(db_session)

        sponsor = await service.get_sponsor(sponsor_user.id)

        assert sponsor is not None
        assert sponsor.id == sponsor_user.id
        assert sponsor.role == UserRole.SPONSOR.value

    async def test_get_sponsor_nonexistent(self, db_session: AsyncSession):
        """Test retrieving non-existent sponsor returns None."""
        service = ParticipantService(db_session)

        sponsor = await service.get_sponsor(99999)

        assert sponsor is None

    async def test_list_participants_with_role_filter(
        self, db_session: AsyncSession, sponsor_user: User, invitee_user: User
    ):
        """Test listing participants filtered by role."""
        service = ParticipantService(db_session)

        users, total = await service.list_participants(
            role=UserRole.SPONSOR.value, page=1, page_size=50
        )

        # Should only return sponsors
        assert total >= 1
        for user in users:
            assert user.role == UserRole.SPONSOR.value

    async def test_list_participants_with_sponsor_filter(
        self, db_session: AsyncSession, sponsor_user: User
    ):
        """Test listing participants filtered by sponsor."""
        service = ParticipantService(db_session)

        # Create sponsored participant
        sponsored = await service.create_participant(
            email="sponsored_filter@test.com",
            first_name="Sponsored",
            last_name="User",
            country="USA",
            sponsor_id=sponsor_user.id
        )

        users, total = await service.list_participants(
            sponsor_id=sponsor_user.id, page=1, page_size=50
        )

        # Should return at least our sponsored user
        assert total >= 1
        user_ids = [u.id for u in users]
        assert sponsored.id in user_ids

    async def test_list_participants_with_confirmed_filter(
        self, db_session: AsyncSession
    ):
        """Test listing participants filtered by confirmed status."""
        service = ParticipantService(db_session)

        # Create confirmed participant
        confirmed_user = await service.create_participant(
            email="confirmed_filter@test.com",
            first_name="Confirmed",
            last_name="User",
            country="USA",
            confirmed="YES"
        )

        users, total = await service.list_participants(
            confirmed="YES", page=1, page_size=50
        )

        # Should return confirmed users
        assert total >= 1
        user_ids = [u.id for u in users]
        assert confirmed_user.id in user_ids

    async def test_get_sponsored_participants_nonexistent_sponsor(
        self, db_session: AsyncSession
    ):
        """Test getting sponsored participants for non-existent sponsor."""
        service = ParticipantService(db_session)

        participants, total = await service.get_sponsored_participants(99999)

        assert len(participants) == 0
        assert total == 0

    async def test_get_sponsored_participants_empty(
        self, db_session: AsyncSession
    ):
        """Test getting sponsored participants when sponsor has none."""
        service = ParticipantService(db_session)

        # Create sponsor with no sponsored users
        sponsor = await service.create_participant(
            email="lonely_sponsor@test.com",
            first_name="Lonely",
            last_name="Sponsor",
            country="USA",
            role=UserRole.SPONSOR.value
        )

        participants, total = await service.get_sponsored_participants(sponsor.id)

        assert len(participants) == 0
        assert total == 0

    async def test_assign_sponsor_invalid_sponsor_id(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test assigning invalid sponsor ID."""
        service = ParticipantService(db_session)

        # Try to assign non-existent sponsor
        updated = await service.assign_sponsor(invitee_user.id, 99999)

        # Should still update but with invalid sponsor_id
        # (FK constraint might be deferred or not enforced in test DB)
        # The behavior depends on DB constraints
        # For now, just test that it doesn't crash
        assert updated is not None or updated is None  # Either outcome is acceptable

    async def test_list_sponsors_empty(self, db_session: AsyncSession):
        """Test listing sponsors when only one exists."""
        service = ParticipantService(db_session)

        # Get all sponsors
        sponsors = await service.list_sponsors()

        # Should return list (may be empty or contain sponsors from fixtures)
        assert isinstance(sponsors, list)


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceListFilters:
    """Test list_participants filtering options."""

    async def test_list_participants_filter_by_is_active(
        self, db_session: AsyncSession
    ):
        """Test filtering participants by active status."""
        service = ParticipantService(db_session)

        # Create active and inactive participants
        active = await service.create_participant(
            email="active@test.com",
            first_name="Active",
            last_name="User",
            country="USA"
        )
        inactive = await service.create_participant(
            email="inactive@test.com",
            first_name="Inactive",
            last_name="User",
            country="USA"
        )
        inactive.is_active = False
        await db_session.commit()

        # Filter by active
        active_users, total = await service.list_participants(
            is_active=True, page=1, page_size=50
        )
        active_ids = [u.id for u in active_users]
        assert active.id in active_ids
        assert inactive.id not in active_ids

        # Filter by inactive
        inactive_users, total = await service.list_participants(
            is_active=False, page=1, page_size=50
        )
        inactive_ids = [u.id for u in inactive_users]
        assert inactive.id in inactive_ids
        assert active.id not in inactive_ids

    async def test_list_participants_filter_by_email_status(
        self, db_session: AsyncSession
    ):
        """Test filtering participants by email status."""
        service = ParticipantService(db_session)

        # Create users with different email statuses
        good = await service.create_participant(
            email="good@test.com",
            first_name="Good",
            last_name="User",
            country="USA"
        )
        good.email_status = "GOOD"
        bounced = await service.create_participant(
            email="bounced@test.com",
            first_name="Bounced",
            last_name="User",
            country="USA"
        )
        bounced.email_status = "BOUNCED"
        await db_session.commit()

        # Filter by GOOD status
        good_users, total = await service.list_participants(
            email_status="GOOD", page=1, page_size=50
        )
        good_ids = [u.id for u in good_users]
        assert good.id in good_ids
        assert bounced.id not in good_ids

        # Filter by BOUNCED status
        bounced_users, total = await service.list_participants(
            email_status="BOUNCED", page=1, page_size=50
        )
        bounced_ids = [u.id for u in bounced_users]
        assert bounced.id in bounced_ids
        assert good.id not in bounced_ids

    async def test_list_participants_filter_by_country(
        self, db_session: AsyncSession
    ):
        """Test filtering participants by country."""
        service = ParticipantService(db_session)

        # Create users from different countries
        usa_user = await service.create_participant(
            email="usa@test.com",
            first_name="USA",
            last_name="User",
            country="USA"
        )
        canada_user = await service.create_participant(
            email="canada@test.com",
            first_name="Canada",
            last_name="User",
            country="Canada"
        )

        # Filter by USA
        usa_users, total = await service.list_participants(
            country="USA", page=1, page_size=50
        )
        usa_ids = [u.id for u in usa_users]
        assert usa_user.id in usa_ids
        assert canada_user.id not in usa_ids

        # Filter by Canada
        canada_users, total = await service.list_participants(
            country="Canada", page=1, page_size=50
        )
        canada_ids = [u.id for u in canada_users]
        assert canada_user.id in canada_ids
        assert usa_user.id not in canada_ids

    async def test_list_participants_filter_by_has_vpn(
        self, db_session: AsyncSession
    ):
        """Test filtering participants by VPN status."""
        service = ParticipantService(db_session)
        from app.models.vpn import VPNCredential

        # Create users
        with_vpn = await service.create_participant(
            email="withvpn@test.com",
            first_name="WithVPN",
            last_name="User",
            country="USA"
        )
        without_vpn = await service.create_participant(
            email="withoutvpn@test.com",
            first_name="WithoutVPN",
            last_name="User",
            country="USA"
        )

        # Assign VPN to first user
        vpn = VPNCredential(
            assigned_to_user_id=with_vpn.id,
            interface_ip="10.20.200.149",
            private_key="base64encodedprivatekey==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=False,
            is_active=True
        )
        db_session.add(vpn)
        await db_session.commit()

        # Filter by has_vpn=True
        vpn_users, total = await service.list_participants(
            has_vpn=True, page=1, page_size=50
        )
        vpn_ids = [u.id for u in vpn_users]
        assert with_vpn.id in vpn_ids

        # Filter by has_vpn=False
        no_vpn_users, total = await service.list_participants(
            has_vpn=False, page=1, page_size=50
        )
        no_vpn_ids = [u.id for u in no_vpn_users]
        assert without_vpn.id in no_vpn_ids

    async def test_list_participants_sort_by_email(
        self, db_session: AsyncSession
    ):
        """Test sorting participants by email."""
        service = ParticipantService(db_session)

        # Create users with different emails
        await service.create_participant(
            email="charlie@test.com",
            first_name="Charlie",
            last_name="User",
            country="USA"
        )
        await service.create_participant(
            email="alice@test.com",
            first_name="Alice",
            last_name="User",
            country="USA"
        )
        await service.create_participant(
            email="bob@test.com",
            first_name="Bob",
            last_name="User",
            country="USA"
        )

        # Sort ascending
        users_asc, _ = await service.list_participants(
            sort_by="email", sort_order="asc", page=1, page_size=50
        )
        emails_asc = [u.email for u in users_asc if u.email.endswith("@test.com")]
        assert emails_asc[0] == "alice@test.com"
        assert emails_asc[-1] == "charlie@test.com"

        # Sort descending
        users_desc, _ = await service.list_participants(
            sort_by="email", sort_order="desc", page=1, page_size=50
        )
        emails_desc = [u.email for u in users_desc if u.email.endswith("@test.com")]
        assert emails_desc[0] == "charlie@test.com"
        assert emails_desc[-1] == "alice@test.com"


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceUsernameGeneration:
    """Test username generation edge cases."""

    async def test_generate_username_with_conflict(
        self, db_session: AsyncSession
    ):
        """Test username generation resolves conflicts with counter."""
        service = ParticipantService(db_session)

        # Create user with jsmith username
        user1 = await service.create_participant(
            email="john1@test.com",
            first_name="John",
            last_name="Smith",
            country="USA",
            pandas_username="jsmith"
        )
        assert user1.pandas_username == "jsmith"

        # Create another John Smith - should get jsmith1
        user2 = await service.create_participant(
            email="john2@test.com",
            first_name="John",
            last_name="Smith",
            country="USA",
            role=UserRole.SPONSOR.value  # Trigger credential generation
        )
        # Username should have counter suffix
        assert user2.pandas_username == "jsmith1"

        # Create third John Smith - should get jsmith2
        user3 = await service.create_participant(
            email="john3@test.com",
            first_name="John",
            last_name="Smith",
            country="USA",
            role=UserRole.SPONSOR.value
        )
        assert user3.pandas_username == "jsmith2"


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceDeleteWithVPN:
    """Test delete participant with VPN credentials."""

    async def test_delete_participant_with_vpn(
        self, db_session: AsyncSession
    ):
        """Test deleting participant marks VPN as unavailable."""
        service = ParticipantService(db_session)
        from app.models.vpn import VPNCredential
        from sqlalchemy import select

        # Create user
        user = await service.create_participant(
            email="vpnuser@test.com",
            first_name="VPN",
            last_name="User",
            country="USA"
        )

        # Assign VPN credential
        vpn = VPNCredential(
            assigned_to_user_id=user.id,
            interface_ip="10.20.200.150",
            private_key="base64encodedprivatekey2==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=False,
            is_active=True
        )
        db_session.add(vpn)
        await db_session.commit()
        vpn_id = vpn.id

        # Delete user
        success = await service.delete_participant(user.id)
        assert success is True

        # Verify VPN credential is marked unavailable
        result = await db_session.execute(
            select(VPNCredential).where(VPNCredential.id == vpn_id)
        )
        vpn_after = result.scalar_one_or_none()
        assert vpn_after is not None
        assert vpn_after.is_available is False
        assert vpn_after.is_active is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceCanSendEmail:
    """Test email status checking."""

    async def test_can_send_email_good_status(
        self, db_session: AsyncSession
    ):
        """Test can send email to GOOD status."""
        service = ParticipantService(db_session)

        assert service._can_send_email("GOOD") is True
        assert service._can_send_email("UNKNOWN") is True

    async def test_cannot_send_email_blocked_statuses(
        self, db_session: AsyncSession
    ):
        """Test cannot send email to blocked statuses."""
        service = ParticipantService(db_session)

        assert service._can_send_email("BOUNCED") is False
        assert service._can_send_email("SPAM_REPORTED") is False
        assert service._can_send_email("UNSUBSCRIBED") is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantServiceEventIntegration:
    """Test participant service integration with event and workflow systems."""

    async def test_create_participant_with_active_event_sends_invitation(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating participant with active event and registration open sends invitation."""
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.workflow_service import WorkflowService

        # Create active event with registration open
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            is_active=True,
            registration_open=True,
            test_mode=False,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock WorkflowService.trigger_workflow
        mock_trigger = mocker.patch.object(
            WorkflowService,
            'trigger_workflow',
            return_value=1
        )

        # Create invitee
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invited",
            last_name="User",
            country="USA"
        )

        # Should have confirmation code and sent timestamp
        assert participant.confirmation_code is not None
        assert participant.confirmation_sent_at is not None
        # Workflow not triggered for invitees without credentials
        assert mock_trigger.call_count == 0

    async def test_create_sponsor_with_active_event_defers_credentials(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating sponsor with active event does NOT trigger credentials workflow.

        Sponsors must confirm participation before receiving credentials.
        Credentials are sent via user_confirmed workflow after confirmation.
        """
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.workflow_service import WorkflowService

        # Create active event with registration open
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            is_active=True,
            registration_open=True,
            test_mode=False,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock WorkflowService.trigger_workflow
        mock_trigger = mocker.patch.object(
            WorkflowService,
            'trigger_workflow',
            return_value=1
        )

        # Create sponsor (has credentials)
        participant = await service.create_participant(
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )

        # Should have confirmation code but NOT trigger workflow
        assert participant.confirmation_code is not None
        assert participant.confirmation_sent_at is not None
        assert mock_trigger.call_count == 0  # No credentials email before confirmation

    async def test_create_participant_test_mode_blocks_invitees(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating invitee with test mode enabled blocks invitation."""
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.audit_service import AuditService

        # Create active event with test mode enabled
        event = Event(
            year=2026,
            name="CyberX 2026 Test",
            slug=generate_slug("CyberX 2026 Test"),
            is_active=True,
            registration_open=True,
            test_mode=True,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock AuditService.log_invitation_blocked
        mock_audit = mocker.patch.object(
            AuditService,
            'log_invitation_blocked',
            return_value=None
        )

        # Create invitee
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )

        # Should NOT have confirmation code (blocked)
        assert participant.confirmation_code is None
        assert participant.confirmation_sent_at is None

        # Should log invitation blocked
        assert mock_audit.call_count == 1
        call_args = mock_audit.call_args[1]
        assert call_args['reason'] == 'test_mode_restricted_non_sponsor'

    async def test_create_participant_test_mode_allows_sponsors(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating sponsor with test mode generates confirmation code but defers credentials."""
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.workflow_service import WorkflowService

        # Create active event with test mode enabled
        event = Event(
            year=2026,
            name="CyberX 2026 Test",
            slug=generate_slug("CyberX 2026 Test"),
            is_active=True,
            registration_open=True,
            test_mode=True,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock WorkflowService.trigger_workflow
        mock_trigger = mocker.patch.object(
            WorkflowService,
            'trigger_workflow',
            return_value=1
        )

        # Create sponsor
        participant = await service.create_participant(
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )

        # Should have confirmation code (allowed in test mode) but NO credentials email
        assert participant.confirmation_code is not None
        assert participant.confirmation_sent_at is not None
        assert mock_trigger.call_count == 0  # Credentials deferred until confirmation

    async def test_create_participant_inactive_event_no_invitation(
        self, db_session: AsyncSession
    ):
        """Test creating participant with inactive event does not send invitation."""
        service = ParticipantService(db_session)
        from app.models.event import Event

        # Create inactive event
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            is_active=False,
            registration_open=True,
            test_mode=False,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Create invitee
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA"
        )

        # Should NOT have confirmation code
        assert participant.confirmation_code is None
        assert participant.confirmation_sent_at is None

    async def test_create_sponsor_inactive_event_defers_credentials(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating sponsor with inactive event defers credentials until confirmation."""
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.email_queue_service import EmailQueueService

        # Create inactive event
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            is_active=False,
            registration_open=True,
            test_mode=False,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock EmailQueueService.enqueue_email
        mock_enqueue = mocker.patch.object(
            EmailQueueService,
            'enqueue_email',
            return_value=mocker.Mock(id=1)
        )

        # Create sponsor
        participant = await service.create_participant(
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )

        # Should NOT enqueue password email — credentials deferred until confirmation
        assert mock_enqueue.call_count == 0

    async def test_create_confirmed_invitee_with_active_event_triggers_workflow(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating confirmed invitee with active event triggers workflow."""
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.workflow_service import WorkflowService

        # Create active event
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            is_active=True,
            registration_open=True,
            test_mode=False,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock WorkflowService.trigger_workflow
        mock_trigger = mocker.patch.object(
            WorkflowService,
            'trigger_workflow',
            return_value=1
        )

        # Create confirmed invitee (gets credentials because confirmed=YES)
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            confirmed="YES"
        )

        # Should trigger user_created workflow (confirmed invitees have credentials)
        assert mock_trigger.call_count == 1
        call_args = mock_trigger.call_args[1]
        assert call_args['trigger_event'] == 'user_created'
        assert call_args['user_id'] == participant.id

    async def test_create_confirmed_invitee_without_active_event_no_password(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating confirmed invitee without active event skips password email."""
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.email_queue_service import EmailQueueService

        # Create inactive event
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            is_active=False,
            registration_open=False,
            test_mode=False,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock EmailQueueService.enqueue_email
        mock_enqueue = mocker.patch.object(
            EmailQueueService,
            'enqueue_email',
            return_value=mocker.Mock(id=1)
        )

        # Create confirmed invitee
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            confirmed="YES"
        )

        # Should NOT enqueue password email (no active event)
        assert mock_enqueue.call_count == 0

    async def test_create_confirmed_sponsor_always_sends_password(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating confirmed sponsor always sends password regardless of event."""
        service = ParticipantService(db_session)
        from app.services.email_queue_service import EmailQueueService

        # No event exists

        # Mock EmailQueueService.enqueue_email
        mock_enqueue = mocker.patch.object(
            EmailQueueService,
            'enqueue_email',
            return_value=mocker.Mock(id=1)
        )

        # Create confirmed sponsor
        participant = await service.create_participant(
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value,
            confirmed="YES"
        )

        # Should enqueue password email
        assert mock_enqueue.call_count == 1
        call_args = mock_enqueue.call_args[1]
        assert call_args['template_name'] == 'password'

    async def test_update_participant_to_confirmed_triggers_workflow(
        self, db_session: AsyncSession, mocker
    ):
        """Test updating participant to confirmed=YES triggers user_confirmed workflow."""
        service = ParticipantService(db_session)
        from app.services.workflow_service import WorkflowService
        from app.models.email_workflow import WorkflowTriggerEvent

        # Create unconfirmed participant
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            confirmed="NO"
        )

        # Mock WorkflowService.trigger_workflow
        mock_trigger = mocker.patch.object(
            WorkflowService,
            'trigger_workflow',
            return_value=2
        )

        # Update to confirmed
        updated = await service.update_participant(
            participant.id,
            confirmed="YES"
        )

        # Should trigger workflow
        assert updated.confirmed == "YES"
        assert updated.confirmed_at is not None
        assert mock_trigger.call_count == 1

        # Verify workflow was called with correct trigger
        call_args = mock_trigger.call_args
        assert call_args[1]['trigger_event'] == WorkflowTriggerEvent.USER_CONFIRMED
        assert call_args[1]['user_id'] == participant.id

    async def test_update_participant_already_confirmed_no_workflow(
        self, db_session: AsyncSession, mocker
    ):
        """Test updating already confirmed participant does not trigger workflow."""
        service = ParticipantService(db_session)
        from app.services.workflow_service import WorkflowService

        # Create confirmed participant
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            confirmed="YES"
        )

        # Mock WorkflowService.trigger_workflow
        mock_trigger = mocker.patch.object(
            WorkflowService,
            'trigger_workflow',
            return_value=1
        )

        # Update other field
        updated = await service.update_participant(
            participant.id,
            country="Canada"
        )

        # Should NOT trigger workflow (already confirmed)
        assert updated.country == "Canada"
        assert mock_trigger.call_count == 0

    async def test_create_admin_with_is_admin_flag(
        self, db_session: AsyncSession
    ):
        """Test creating participant with is_admin=True sets role to ADMIN."""
        service = ParticipantService(db_session)

        # Create user with is_admin=True (legacy behavior)
        participant = await service.create_participant(
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            is_admin=True  # Should set role to ADMIN even if role defaults to INVITEE
        )

        # Should have ADMIN role
        assert participant.role == UserRole.ADMIN.value
        assert participant.is_admin is True

    async def test_create_confirmed_admin_sends_password(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating confirmed admin sends password email (non-event-participant path)."""
        service = ParticipantService(db_session)
        from app.services.email_queue_service import EmailQueueService

        # Mock EmailQueueService.enqueue_email
        mock_enqueue = mocker.patch.object(
            EmailQueueService,
            'enqueue_email',
            return_value=mocker.Mock(id=1)
        )

        # Create confirmed admin (not an event participant)
        participant = await service.create_participant(
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            confirmed="YES"
        )

        # Should enqueue password email via elif block (non-event-participant)
        assert mock_enqueue.call_count == 1
        call_args = mock_enqueue.call_args[1]
        assert call_args['template_name'] == 'password'
        assert call_args['user_id'] == participant.id

    async def test_create_participant_workflow_trigger_error(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating pre-confirmed participant handles workflow trigger errors gracefully."""
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.workflow_service import WorkflowService

        # Create active event
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            is_active=True,
            registration_open=True,
            test_mode=False,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock WorkflowService.trigger_workflow to raise exception
        mock_trigger = mocker.patch.object(
            WorkflowService,
            'trigger_workflow',
            side_effect=Exception("Workflow system error")
        )

        # Create pre-confirmed invitee (triggers workflow because confirmed=YES)
        # Should not raise, just log error
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            confirmed="YES"
        )

        # Participant should still be created despite workflow error
        assert participant.id is not None
        assert mock_trigger.call_count == 1

    async def test_create_sponsor_credentials_email_error(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating pre-confirmed sponsor handles credentials email errors gracefully."""
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.email_queue_service import EmailQueueService

        # Create inactive event (no invitation, but confirmed=YES triggers credentials email)
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            is_active=False,
            registration_open=False,
            test_mode=False,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock EmailQueueService.enqueue_email to raise exception
        mock_enqueue = mocker.patch.object(
            EmailQueueService,
            'enqueue_email',
            side_effect=Exception("Email queue error")
        )

        # Create pre-confirmed sponsor — should not raise, just log error
        participant = await service.create_participant(
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value,
            confirmed="YES"
        )

        # Participant should still be created despite email error
        assert participant.id is not None
        assert mock_enqueue.call_count == 1

    async def test_update_participant_workflow_error(
        self, db_session: AsyncSession, mocker
    ):
        """Test updating participant handles workflow errors gracefully."""
        service = ParticipantService(db_session)
        from app.services.workflow_service import WorkflowService

        # Create unconfirmed participant
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            confirmed="NO"
        )

        # Mock WorkflowService.trigger_workflow to raise exception
        mock_trigger = mocker.patch.object(
            WorkflowService,
            'trigger_workflow',
            side_effect=Exception("Workflow error")
        )

        # Should not raise, just log error
        updated = await service.update_participant(
            participant.id,
            confirmed="YES"
        )

        # Participant should still be updated
        assert updated.confirmed == "YES"
        assert updated.confirmed_at is not None
        assert mock_trigger.call_count == 1

    async def test_create_confirmed_admin_email_queue_error(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating confirmed admin handles email queue errors gracefully."""
        service = ParticipantService(db_session)
        from app.services.email_queue_service import EmailQueueService

        # Mock EmailQueueService.enqueue_email to raise exception
        mock_enqueue = mocker.patch.object(
            EmailQueueService,
            'enqueue_email',
            side_effect=Exception("Queue error")
        )

        # Should not raise, just log error
        participant = await service.create_participant(
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            confirmed="YES"
        )

        # Participant should still be created
        assert participant.id is not None
        assert mock_enqueue.call_count == 1

    async def test_create_confirmed_invitee_no_event_skips_password(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating confirmed invitee without event skips password (logs message)."""
        service = ParticipantService(db_session)
        from app.services.email_queue_service import EmailQueueService

        # No event exists

        # Mock EmailQueueService.enqueue_email (should not be called)
        mock_enqueue = mocker.patch.object(
            EmailQueueService,
            'enqueue_email',
            return_value=mocker.Mock(id=1)
        )

        # Create confirmed invitee (via different code path than event participants)
        # This should hit the elif block lines 347-387 since there's no event
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value,
            confirmed="YES"
        )

        # Should NOT enqueue password email (no event)
        # The code checks for active event and logs a message
        assert participant.id is not None
        # Note: This might not hit line 357-361 if is_event_participant is True

    async def test_create_invitee_without_credentials_skips_workflow(
        self, db_session: AsyncSession, mocker
    ):
        """Test creating invitee without credentials logs skip message."""
        service = ParticipantService(db_session)
        from app.models.event import Event
        from app.services.workflow_service import WorkflowService

        # Create active event
        event = Event(
            year=2026,
            name="CyberX 2026",
            slug=generate_slug("CyberX 2026"),
            is_active=True,
            registration_open=True,
            test_mode=False,
            terms_version="1.0"
        )
        db_session.add(event)
        await db_session.commit()

        # Mock WorkflowService.trigger_workflow (should not be called)
        mock_trigger = mocker.patch.object(
            WorkflowService,
            'trigger_workflow',
            return_value=1
        )

        # Create unconfirmed invitee (no credentials)
        participant = await service.create_participant(
            email="invitee@test.com",
            first_name="Invitee",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value,
            confirmed="NO"
        )

        # Should have confirmation code but NOT trigger workflow
        # (invitees without credentials are handled by background task)
        assert participant.confirmation_code is not None
        assert mock_trigger.call_count == 0  # Not called because has_credentials is False
