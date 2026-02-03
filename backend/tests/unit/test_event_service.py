"""
Unit tests for EventService.

Tests event management including CRUD operations, active event queries,
and invitation control logic.
"""

import pytest
from datetime import datetime, timezone, date
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.event_service import EventService
from app.models.event import Event


@pytest.mark.unit
@pytest.mark.asyncio
class TestEventServiceRetrieval:
    """Test event retrieval operations."""

    async def test_get_event_by_id(self, db_session: AsyncSession):
        """Test retrieving event by ID."""
        service = EventService(db_session)

        # Create event
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True
        )
        db_session.add(event)
        await db_session.commit()

        # Retrieve
        retrieved = await service.get_event(event.id)
        assert retrieved is not None
        assert retrieved.id == event.id
        assert retrieved.year == 2026
        assert retrieved.name == "CyberX 2026"

    async def test_get_nonexistent_event(self, db_session: AsyncSession):
        """Test retrieving non-existent event returns None."""
        service = EventService(db_session)
        event = await service.get_event(99999)
        assert event is None

    async def test_get_event_by_year(self, db_session: AsyncSession):
        """Test retrieving event by year."""
        service = EventService(db_session)

        # Create events for different years
        event_2025 = Event(
            year=2025,
            name="CyberX 2025",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 7)
        )
        event_2026 = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7)
        )
        db_session.add_all([event_2025, event_2026])
        await db_session.commit()

        # Get by year
        retrieved = await service.get_event_by_year(2026)
        assert retrieved is not None
        assert retrieved.year == 2026
        assert retrieved.name == "CyberX 2026"

    async def test_get_active_event(self, db_session: AsyncSession):
        """Test retrieving the active event."""
        service = EventService(db_session)

        # Create multiple events, only one active
        inactive_event = Event(
            year=2025,
            name="CyberX 2025",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 7),
            is_active=False
        )
        active_event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True
        )
        db_session.add_all([inactive_event, active_event])
        await db_session.commit()

        # Get active
        retrieved = await service.get_active_event()
        assert retrieved is not None
        assert retrieved.id == active_event.id
        assert retrieved.is_active is True

    async def test_get_active_event_none_active(self, db_session: AsyncSession):
        """Test retrieving active event when none are active."""
        service = EventService(db_session)

        # Create inactive event
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=False
        )
        db_session.add(event)
        await db_session.commit()

        # Should return None
        active = await service.get_active_event()
        assert active is None

    async def test_get_current_event_alias(self, db_session: AsyncSession):
        """Test get_current_event is alias for get_active_event."""
        service = EventService(db_session)

        # Create active event
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True
        )
        db_session.add(event)
        await db_session.commit()

        # Both methods should return same event
        current = await service.get_current_event()
        active = await service.get_active_event()

        assert current is not None
        assert active is not None
        assert current.id == active.id

    async def test_list_events_excludes_archived(self, db_session: AsyncSession):
        """Test listing events excludes archived by default."""
        service = EventService(db_session)

        # Create events
        active_event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_archived=False
        )
        archived_event = Event(
            year=2024,
            name="CyberX 2024",
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 7),
            is_archived=True
        )
        db_session.add_all([active_event, archived_event])
        await db_session.commit()

        # List without archived
        events = await service.list_events(include_archived=False)
        years = [e.year for e in events]

        assert 2026 in years
        assert 2024 not in years  # Archived excluded

    async def test_list_events_includes_archived(self, db_session: AsyncSession):
        """Test listing events can include archived."""
        service = EventService(db_session)

        # Create events
        active_event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_archived=False
        )
        archived_event = Event(
            year=2024,
            name="CyberX 2024",
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 7),
            is_archived=True
        )
        db_session.add_all([active_event, archived_event])
        await db_session.commit()

        # List with archived
        events = await service.list_events(include_archived=True)
        years = [e.year for e in events]

        assert 2026 in years
        assert 2024 in years  # Archived included


@pytest.mark.unit
@pytest.mark.asyncio
class TestEventServiceBusinessLogic:
    """Test event business logic operations."""

    async def test_is_event_active_true(self, db_session: AsyncSession):
        """Test checking if event is active returns True."""
        service = EventService(db_session)

        # Create active event
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True
        )
        db_session.add(event)
        await db_session.commit()

        is_active = await service.is_event_active()
        assert is_active is True

    async def test_is_event_active_false(self, db_session: AsyncSession):
        """Test checking if event is active returns False when none active."""
        service = EventService(db_session)

        # Create inactive event
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=False
        )
        db_session.add(event)
        await db_session.commit()

        is_active = await service.is_event_active()
        assert is_active is False

    async def test_can_send_invitations_true(self, db_session: AsyncSession):
        """Test can send invitations when event is active and registration open."""
        service = EventService(db_session)

        # Create active event with registration open
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True,
            registration_open=True
        )
        db_session.add(event)
        await db_session.commit()

        can_send = await service.can_send_invitations()
        assert can_send is True

    async def test_can_send_invitations_registration_closed(
        self, db_session: AsyncSession
    ):
        """Test cannot send invitations when registration is closed."""
        service = EventService(db_session)

        # Create active event but registration closed
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True,
            registration_open=False
        )
        db_session.add(event)
        await db_session.commit()

        can_send = await service.can_send_invitations()
        assert can_send is False

    async def test_can_send_invitations_event_inactive(
        self, db_session: AsyncSession
    ):
        """Test cannot send invitations when event is inactive."""
        service = EventService(db_session)

        # Create inactive event
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=False,
            registration_open=True
        )
        db_session.add(event)
        await db_session.commit()

        can_send = await service.can_send_invitations()
        assert can_send is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestEventServiceMutation:
    """Test event creation, update, and deletion operations."""

    async def test_create_event(self, db_session: AsyncSession):
        """Test creating a new event."""
        service = EventService(db_session)

        event = await service.create_event(
            year=2027,
            name="CyberX 2027",
            start_date=date(2027, 6, 1),
            end_date=date(2027, 6, 7),
            event_time="9:00 AM",
            event_location="Virtual",
            is_active=False
        )

        assert event.id is not None
        assert event.year == 2027
        assert event.name == "CyberX 2027"
        assert event.is_active is False

    async def test_update_event(self, db_session: AsyncSession):
        """Test updating event fields."""
        service = EventService(db_session)

        # Create event
        event = await service.create_event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=False
        )

        # Update
        updated = await service.update_event(
            event.id,
            name="CyberX 2026 - Red Team",
            is_active=True,
            registration_open=True
        )

        assert updated is not None
        assert updated.name == "CyberX 2026 - Red Team"
        assert updated.is_active is True
        assert updated.registration_open is True

    async def test_update_nonexistent_event(self, db_session: AsyncSession):
        """Test updating non-existent event returns None."""
        service = EventService(db_session)

        result = await service.update_event(99999, name="Test")
        assert result is None

    async def test_delete_event(self, db_session: AsyncSession):
        """Test deleting an event."""
        service = EventService(db_session)

        # Create event
        event = await service.create_event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7)
        )
        event_id = event.id

        # Delete
        success = await service.delete_event(event_id)
        assert success is True

        # Verify deleted
        deleted = await service.get_event(event_id)
        assert deleted is None

    async def test_delete_nonexistent_event(self, db_session: AsyncSession):
        """Test deleting non-existent event returns False."""
        service = EventService(db_session)

        success = await service.delete_event(99999)
        assert success is False

    async def test_deactivate_other_events(self, db_session: AsyncSession):
        """Test deactivating all events except specified one."""
        service = EventService(db_session)

        # Create multiple active events
        event_2025 = Event(
            year=2025,
            name="CyberX 2025",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 7),
            is_active=True
        )
        event_2026 = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True
        )
        event_2027 = Event(
            year=2027,
            name="CyberX 2027",
            start_date=date(2027, 6, 1),
            end_date=date(2027, 6, 7),
            is_active=True
        )
        db_session.add_all([event_2025, event_2026, event_2027])
        await db_session.commit()

        # Deactivate all except 2026
        await service.deactivate_other_events(event_2026.id)
        await db_session.commit()

        # Refresh to get updated data
        await db_session.refresh(event_2025)
        await db_session.refresh(event_2026)
        await db_session.refresh(event_2027)

        # Only 2026 should be active
        assert event_2025.is_active is False
        assert event_2026.is_active is True
        assert event_2027.is_active is False

    async def test_deactivate_other_events_when_none_active(
        self, db_session: AsyncSession
    ):
        """Test deactivating other events when no other events are active."""
        service = EventService(db_session)

        # Create one active event and inactive events
        inactive_event = Event(
            year=2025,
            name="CyberX 2025",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 7),
            is_active=False
        )
        active_event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=True
        )
        db_session.add_all([inactive_event, active_event])
        await db_session.commit()

        # Deactivate others (should be no-op since only one is active)
        await service.deactivate_other_events(active_event.id)
        await db_session.commit()

        # Refresh
        await db_session.refresh(inactive_event)
        await db_session.refresh(active_event)

        # States should remain unchanged
        assert inactive_event.is_active is False
        assert active_event.is_active is True

    async def test_list_events_empty(self, db_session: AsyncSession):
        """Test listing events when none exist."""
        service = EventService(db_session)

        events = await service.list_events()

        assert len(events) == 0

    async def test_list_events_all_archived(self, db_session: AsyncSession):
        """Test listing events when all are archived."""
        service = EventService(db_session)

        # Create only archived events
        archived_event = Event(
            year=2024,
            name="CyberX 2024",
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 7),
            is_archived=True
        )
        db_session.add(archived_event)
        await db_session.commit()

        # List without archived
        events = await service.list_events(include_archived=False)

        assert len(events) == 0

    async def test_activate_event_deactivates_others(
        self, db_session: AsyncSession
    ):
        """Test that activating an event deactivates all others."""
        service = EventService(db_session)

        # Create multiple events
        event_2025 = await service.create_event(
            year=2025,
            name="CyberX 2025",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 7),
            is_active=True
        )
        event_2026 = await service.create_event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            is_active=False
        )

        # Activate 2026 (should deactivate 2025)
        await service.update_event(event_2026.id, is_active=True)
        await service.deactivate_other_events(event_2026.id)
        await db_session.commit()

        # Refresh
        await db_session.refresh(event_2025)
        await db_session.refresh(event_2026)

        assert event_2025.is_active is False
        assert event_2026.is_active is True

    async def test_get_event_by_year_nonexistent(self, db_session: AsyncSession):
        """Test retrieving event by year when year doesn't exist."""
        service = EventService(db_session)

        # Create event for 2026
        event = Event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7)
        )
        db_session.add(event)
        await db_session.commit()

        # Try to get 2099
        result = await service.get_event_by_year(2099)
        assert result is None

    async def test_create_event_with_minimal_fields(self, db_session: AsyncSession):
        """Test creating event with only required fields."""
        service = EventService(db_session)

        event = await service.create_event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7)
        )

        assert event.id is not None
        assert event.year == 2026
        assert event.name == "CyberX 2026"
        assert event.is_active is False  # Default
        assert event.registration_open is False  # Default

    async def test_update_event_partial_fields(self, db_session: AsyncSession):
        """Test updating only some event fields."""
        service = EventService(db_session)

        # Create event
        event = await service.create_event(
            year=2026,
            name="CyberX 2026",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 7),
            event_time="9:00 AM",
            event_location="Building A"
        )

        original_location = event.event_location

        # Update only name and time
        updated = await service.update_event(
            event.id,
            name="CyberX 2026 - Updated",
            event_time="10:00 AM"
        )

        assert updated.name == "CyberX 2026 - Updated"
        assert updated.event_time == "10:00 AM"
        assert updated.event_location == original_location  # Unchanged
