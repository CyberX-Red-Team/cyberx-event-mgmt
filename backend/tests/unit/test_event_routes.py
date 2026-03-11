"""Unit tests for event API routes.

Tests route-level logic, validation, error handling, and response formatting.
All service dependencies are mocked to isolate route behavior.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock

from app.api.routes.event import (
    list_events,
    get_active_event,
    get_event,
    create_event,
    update_event,
    delete_event,
    list_event_participants,
    bulk_invite_to_event,
    get_my_participation_history,
    confirm_my_participation,
    decline_my_participation,
    get_chronic_non_participants,
    get_recommended_removals
)
from app.schemas.event import (
    EventCreate,
    EventUpdate,
    BulkInviteRequest,
    ConfirmParticipationRequest
)
from app.models.user import User, UserRole
from app.models.event import Event


@pytest.mark.unit
@pytest.mark.asyncio
class TestEventListingRoutes:
    """Test event listing and retrieval routes."""

    async def test_list_events(self, mocker):
        """Test listing all events."""
        # Mock user
        mock_user = User(
            id=1,
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )

        # Mock events
        mock_event1 = Mock()
        mock_event1.id = 1
        mock_event1.year = 2025
        mock_event1.name = "CyberX 2025"
        mock_event1.slug = "cyberx-2025"
        mock_event1.start_date = datetime(2025, 7, 1, tzinfo=timezone.utc)
        mock_event1.end_date = datetime(2025, 7, 7, tzinfo=timezone.utc)
        mock_event1.event_time = "10:00 AM - 6:00 PM"
        mock_event1.event_location = "Las Vegas, NV"
        mock_event1.terms_version = "1.0"
        mock_event1.is_active = True
        mock_event1.created_at = datetime.now(timezone.utc)
        mock_event1.updated_at = datetime.now(timezone.utc)

        mock_event2 = Mock()
        mock_event2.id = 2
        mock_event2.year = 2026
        mock_event2.name = "CyberX 2026"
        mock_event2.slug = "cyberx-2026"
        mock_event2.start_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
        mock_event2.end_date = datetime(2026, 7, 7, tzinfo=timezone.utc)
        mock_event2.event_time = "10:00 AM - 6:00 PM"
        mock_event2.event_location = "Las Vegas, NV"
        mock_event2.terms_version = "1.0"
        mock_event2.is_active = False
        mock_event2.created_at = datetime.now(timezone.utc)
        mock_event2.updated_at = datetime.now(timezone.utc)

        # Mock service
        mock_service = mocker.Mock()
        mock_service.list_events = mocker.AsyncMock(return_value=[mock_event1, mock_event2])
        mock_service.get_event_statistics = mocker.AsyncMock(return_value={
            "total_invited": 100,
            "total_confirmed": 75,
            "total_declined": 10,
            "total_no_response": 15
        })

        result = await list_events(current_user=mock_user, service=mock_service)

        assert result.total == 2
        assert len(result.items) == 2
        assert result.items[0].year == 2025
        assert result.items[0].total_invited == 100
        assert result.items[0].total_confirmed == 75

    async def test_get_active_event_exists(self, mocker):
        """Test getting active event when one exists."""
        mock_user = User(
            id=1,
            email="user@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )

        mock_event = Mock()
        mock_event.id = 1
        mock_event.year = 2026
        mock_event.name = "CyberX 2026"
        mock_event.slug = "cyberx-2026"
        mock_event.start_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
        mock_event.end_date = datetime(2026, 7, 7, tzinfo=timezone.utc)
        mock_event.event_time = "10:00 AM - 6:00 PM"
        mock_event.event_location = "Las Vegas, NV"
        mock_event.terms_version = "1.0"
        mock_event.is_active = True
        mock_event.vpn_available = True
        mock_event.test_mode = False
        mock_event.ssh_private_key = None
        mock_event.created_at = datetime.now(timezone.utc)
        mock_event.updated_at = datetime.now(timezone.utc)

        mock_service = mocker.Mock()
        mock_service.get_active_event = mocker.AsyncMock(return_value=mock_event)

        # Mock db session for participation query
        mock_part_result = mocker.Mock()
        mock_part_result.scalar_one_or_none = mocker.Mock(return_value=None)
        mock_db = mocker.AsyncMock()
        mock_db.execute = mocker.AsyncMock(return_value=mock_part_result)

        result = await get_active_event(current_user=mock_user, service=mock_service, db=mock_db)

        assert result["active"] is True
        assert result["event"].year == 2026
        assert result["event"].vpn_available is True

    async def test_get_active_event_none_exists(self, mocker):
        """Test getting active event when none exists."""
        mock_user = User(
            id=1,
            email="user@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )

        mock_service = mocker.Mock()
        mock_service.get_active_event = mocker.AsyncMock(return_value=None)

        mock_db = mocker.AsyncMock()

        result = await get_active_event(current_user=mock_user, service=mock_service, db=mock_db)

        assert result["active"] is False
        assert result["event"] is None

    async def test_get_event_by_id_success(self, mocker):
        """Test getting specific event by ID."""
        mock_user = User(
            id=1,
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )

        mock_event = Mock()
        mock_event.id = 1
        mock_event.year = 2026
        mock_event.name = "CyberX 2026"
        mock_event.slug = "cyberx-2026"
        mock_event.start_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
        mock_event.end_date = datetime(2026, 7, 7, tzinfo=timezone.utc)
        mock_event.event_time = "10:00 AM - 6:00 PM"
        mock_event.event_location = "Las Vegas, NV"
        mock_event.terms_version = "1.0"
        mock_event.is_active = True
        mock_event.vpn_available = True
        mock_event.test_mode = False
        mock_event.created_at = datetime.now(timezone.utc)
        mock_event.updated_at = datetime.now(timezone.utc)

        mock_service = mocker.Mock()
        mock_service.get_event = mocker.AsyncMock(return_value=mock_event)

        result = await get_event(event_id=1, current_user=mock_user, service=mock_service)

        assert result.id == 1
        assert result.year == 2026
        assert result.name == "CyberX 2026"

    async def test_get_event_not_found(self, mocker):
        """Test getting non-existent event."""
        mock_user = User(
            id=1,
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )

        mock_service = mocker.Mock()
        mock_service.get_event = mocker.AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await get_event(event_id=999, current_user=mock_user, service=mock_service)


@pytest.mark.unit
@pytest.mark.asyncio
class TestEventManagementRoutes:
    """Test event CRUD routes (admin only)."""

    async def test_create_event_success(self, mocker):
        """Test creating a new event."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = EventCreate(
            year=2027,
            name="CyberX 2027",
            start_date=datetime(2027, 7, 1, tzinfo=timezone.utc),
            end_date=datetime(2027, 7, 7, tzinfo=timezone.utc),
            terms_version="1.0",
            terms_content="Terms and conditions...",
            is_active=False
        )

        mock_event = Mock()
        mock_event.id = 1
        mock_event.year = 2027
        mock_event.name = "CyberX 2027"
        mock_event.slug = "cyberx-2027"
        mock_event.start_date = data.start_date
        mock_event.end_date = data.end_date
        mock_event.event_time = None
        mock_event.event_location = None
        mock_event.terms_version = "1.0"
        mock_event.is_active = False
        mock_event.vpn_available = False
        mock_event.test_mode = False
        mock_event.created_at = datetime.now(timezone.utc)
        mock_event.updated_at = datetime.now(timezone.utc)

        mock_service = mocker.Mock()
        mock_service.get_event_by_slug = mocker.AsyncMock(return_value=None)
        mock_service.create_event = mocker.AsyncMock(return_value=mock_event)

        result = await create_event(data=data, current_user=mock_user, service=mock_service)

        assert result.year == 2027
        assert result.name == "CyberX 2027"
        mock_service.create_event.assert_called_once()

    async def test_create_event_year_already_exists(self, mocker):
        """Test creating event for year that already exists."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = EventCreate(
            year=2026,
            name="CyberX 2026",
            start_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 7, 7, tzinfo=timezone.utc),
            terms_version="1.0",
            terms_content="Terms...",
            is_active=False
        )

        existing_event = Mock(id=1, year=2026, slug="cyberx-2026")

        mock_service = mocker.Mock()
        mock_service.get_event_by_slug = mocker.AsyncMock(return_value=existing_event)

        with pytest.raises(Exception) as exc_info:
            await create_event(data=data, current_user=mock_user, service=mock_service)

    async def test_update_event_success(self, mocker):
        """Test updating an event."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = EventUpdate(
            name="Updated Event Name",
            is_active=True
        )

        old_event = Mock(
            id=1,
            year=2026,
            is_active=False,
            test_mode=False,
            registration_open=False
        )

        updated_event = Mock()
        updated_event.id = 1
        updated_event.year = 2026
        updated_event.name = "Updated Event Name"
        updated_event.slug = "updated-event-name"
        updated_event.start_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
        updated_event.end_date = datetime(2026, 7, 7, tzinfo=timezone.utc)
        updated_event.event_time = "10:00 AM - 6:00 PM"
        updated_event.event_location = "Las Vegas, NV"
        updated_event.terms_version = "1.0"
        updated_event.is_active = True
        updated_event.vpn_available = False
        updated_event.test_mode = False
        updated_event.registration_open = False
        updated_event.created_at = datetime.now(timezone.utc)
        updated_event.updated_at = datetime.now(timezone.utc)

        mock_service = mocker.Mock()
        mock_service.get_event = mocker.AsyncMock(return_value=old_event)
        mock_service.update_event = mocker.AsyncMock(return_value=updated_event)

        # Mock schedule_invitation_emails to avoid import issues
        mocker.patch('app.tasks.invitation_emails.schedule_invitation_emails')

        result = await update_event(event_id=1, data=data, current_user=mock_user, service=mock_service)

        assert result.name == "Updated Event Name"
        assert result.is_active is True

    async def test_update_event_not_found(self, mocker):
        """Test updating non-existent event."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = EventUpdate(name="Updated Name")

        mock_service = mocker.Mock()
        mock_service.get_event = mocker.AsyncMock(return_value=None)

        with pytest.raises(Exception) as exc_info:
            await update_event(event_id=999, data=data, current_user=mock_user, service=mock_service)

    async def test_delete_event_success(self, mocker):
        """Test deleting an event."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        mock_service = mocker.Mock()
        mock_service.delete_event = mocker.AsyncMock(return_value=True)

        result = await delete_event(event_id=1, current_user=mock_user, service=mock_service)

        assert result["message"] == "Event deleted successfully"

    async def test_delete_event_not_found(self, mocker):
        """Test deleting non-existent event."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        mock_service = mocker.Mock()
        mock_service.delete_event = mocker.AsyncMock(return_value=False)

        with pytest.raises(Exception) as exc_info:
            await delete_event(event_id=999, current_user=mock_user, service=mock_service)


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipationManagementRoutes:
    """Test participation management routes."""

    async def test_list_event_participants(self, mocker):
        """Test listing participants for an event."""
        mock_user = User(
            id=1,
            email="sponsor@test.com",
            first_name="Sponsor",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )

        mock_event = Mock()
        mock_event.id = 1
        mock_event.year = 2026
        mock_event.name = "CyberX 2026"
        mock_event.slug = "cyberx-2026"

        mock_participation = Mock()
        mock_participation.id = 1
        mock_participation.user_id = 2
        mock_participation.event_id = 1
        mock_participation.status = "confirmed"
        mock_participation.invited_at = datetime.now(timezone.utc)
        mock_participation.terms_accepted_at = datetime.now(timezone.utc)
        mock_participation.confirmed_at = datetime.now(timezone.utc)
        mock_participation.declined_at = None
        mock_participation.declined_reason = None
        mock_participation.created_at = datetime.now(timezone.utc)
        mock_participation.updated_at = datetime.now(timezone.utc)

        mock_service = mocker.Mock()
        mock_service.get_event = mocker.AsyncMock(return_value=mock_event)
        mock_service.get_event_participants = mocker.AsyncMock(return_value=([mock_participation], 1))

        result = await list_event_participants(
            event_id=1,
            page=1,
            page_size=50,
            status=None,
            current_user=mock_user,
            service=mock_service
        )

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].status == "confirmed"

    async def test_bulk_invite_to_event_success(self, mocker):
        """Test bulk inviting users to an event."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = BulkInviteRequest(
            event_id=1,
            user_ids=[2, 3, 4, 5]
        )

        mock_event = Mock(id=1, year=2026, name="CyberX 2026", slug="cyberx-2026")

        mock_service = mocker.Mock()
        mock_service.get_event = mocker.AsyncMock(return_value=mock_event)
        mock_service.bulk_invite_to_event = mocker.AsyncMock(return_value=(4, 0, []))

        result = await bulk_invite_to_event(
            event_id=1,
            data=data,
            current_user=mock_user,
            service=mock_service
        )

        assert result.success is True
        assert result.invited_count == 4
        assert result.already_invited_count == 0

    async def test_bulk_invite_event_id_mismatch(self, mocker):
        """Test bulk invite with mismatched event ID."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = BulkInviteRequest(
            event_id=2,
            user_ids=[2, 3, 4]
        )

        mock_service = mocker.Mock()

        with pytest.raises(Exception) as exc_info:
            await bulk_invite_to_event(event_id=1, data=data, current_user=mock_user, service=mock_service)


@pytest.mark.unit
@pytest.mark.asyncio
class TestParticipantSelfServiceRoutes:
    """Test participant self-service routes."""

    async def test_get_my_participation_history(self, mocker):
        """Test getting user's participation history."""
        mock_user = Mock()
        mock_user.id = 1
        mock_user.email = "user@test.com"
        mock_user.first_name = "Test"
        mock_user.last_name = "User"
        mock_user.country = "USA"
        mock_user.role = UserRole.INVITEE.value
        mock_user.years_invited = 3
        mock_user.years_participated = 2
        mock_user.participation_rate = 0.67
        mock_user.is_chronic_non_participant = False
        mock_user.should_recommend_removal = False

        mock_event = Mock()
        mock_event.id = 1
        mock_event.year = 2026
        mock_event.name = "CyberX 2026"
        mock_event.slug = "cyberx-2026"

        mock_participation = Mock()
        mock_participation.id = 1
        mock_participation.user_id = 1
        mock_participation.event_id = 1
        mock_participation.status = "confirmed"
        mock_participation.invited_at = datetime.now(timezone.utc)
        mock_participation.terms_accepted_at = datetime.now(timezone.utc)
        mock_participation.confirmed_at = datetime.now(timezone.utc)
        mock_participation.declined_at = None
        mock_participation.declined_reason = None
        mock_participation.created_at = datetime.now(timezone.utc)
        mock_participation.updated_at = datetime.now(timezone.utc)
        mock_participation.event = mock_event

        mock_service = mocker.Mock()
        mock_service.get_user_participation_history = mocker.AsyncMock(return_value=[mock_participation])

        result = await get_my_participation_history(current_user=mock_user, service=mock_service)

        assert result.user_id == 1
        assert result.total_years_invited == 3
        assert result.total_years_participated == 2
        assert len(result.history) == 1

    async def test_confirm_participation_success(self, mocker):
        """Test confirming participation."""
        mock_user = User(
            id=1,
            email="user@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )

        data = ConfirmParticipationRequest(
            event_id=1,
            accept_terms=True
        )

        mock_participation = Mock()
        mock_participation.id = 1
        mock_participation.user_id = 1
        mock_participation.event_id = 1
        mock_participation.status = "confirmed"
        mock_participation.invited_at = datetime.now(timezone.utc)
        mock_participation.terms_accepted_at = datetime.now(timezone.utc)
        mock_participation.confirmed_at = datetime.now(timezone.utc)
        mock_participation.declined_at = None
        mock_participation.declined_reason = None
        mock_participation.created_at = datetime.now(timezone.utc)
        mock_participation.updated_at = datetime.now(timezone.utc)

        mock_service = mocker.Mock()
        mock_service.confirm_participation = mocker.AsyncMock(
            return_value=(True, "Participation confirmed", mock_participation)
        )

        result = await confirm_my_participation(data=data, current_user=mock_user, service=mock_service)

        assert result.success is True
        assert result.message == "Participation confirmed"
        assert result.participation.status == "confirmed"

    async def test_confirm_participation_failure(self, mocker):
        """Test confirming participation failure."""
        mock_user = User(
            id=1,
            email="user@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )

        data = ConfirmParticipationRequest(
            event_id=1,
            accept_terms=False
        )

        mock_service = mocker.Mock()
        mock_service.confirm_participation = mocker.AsyncMock(
            return_value=(False, "Terms not accepted", None)
        )

        with pytest.raises(Exception) as exc_info:
            await confirm_my_participation(data=data, current_user=mock_user, service=mock_service)

    async def test_decline_participation_success(self, mocker):
        """Test declining participation."""
        mock_user = User(
            id=1,
            email="user@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )

        mock_participation = Mock(
            id=1,
            user_id=1,
            event_id=1,
            status="declined"
        )

        mock_service = mocker.Mock()
        mock_service.decline_participation = mocker.AsyncMock(
            return_value=(True, "Participation declined", mock_participation)
        )

        result = await decline_my_participation(
            event_id=1,
            reason="Schedule conflict",
            current_user=mock_user,
            service=mock_service
        )

        assert result["success"] is True
        assert result["message"] == "Participation declined"


@pytest.mark.unit
@pytest.mark.asyncio
class TestAdminReportRoutes:
    """Test admin report routes."""

    async def test_get_chronic_non_participants(self, mocker):
        """Test getting chronic non-participants."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        mock_chronic_user = Mock(
            id=2,
            email="chronic@test.com",
            first_name="Chronic",
            last_name="NonParticipant",
            years_invited=5,
            years_participated=0
        )

        mock_service = mocker.Mock()
        mock_service.get_chronic_non_participants = mocker.AsyncMock(return_value=[mock_chronic_user])

        result = await get_chronic_non_participants(current_user=mock_user, service=mock_service)

        assert result["total"] == 1
        assert len(result["users"]) == 1
        assert result["users"][0]["email"] == "chronic@test.com"
        assert result["users"][0]["years_invited"] == 5

    async def test_get_recommended_removals(self, mocker):
        """Test getting recommended removals."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        mock_removal_user = Mock(
            id=2,
            email="remove@test.com",
            first_name="Should",
            last_name="Remove",
            years_invited=10,
            years_participated=1,
            participation_rate=0.1,
            is_chronic_non_participant=True
        )

        mock_service = mocker.Mock()
        mock_service.get_recommended_removals = mocker.AsyncMock(return_value=[mock_removal_user])

        result = await get_recommended_removals(current_user=mock_user, service=mock_service)

        assert result["total"] == 1
        assert len(result["users"]) == 1
        assert result["users"][0]["email"] == "remove@test.com"
        assert result["users"][0]["participation_rate"] == 0.1
