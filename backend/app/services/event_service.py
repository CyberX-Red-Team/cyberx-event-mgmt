"""Event service for managing events and participation tracking."""
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.event import Event, EventParticipation, ParticipationStatus


class EventService:
    """Service for managing events and participation."""

    def __init__(self, session: AsyncSession):
        """Initialize event service."""
        self.session = session

    # ============== Invitation Control Methods ==============

    async def get_current_event(self) -> Optional[Event]:
        """Get the currently active event (alias for get_active_event)."""
        return await self.get_active_event()

    async def is_event_active(self) -> bool:
        """Check if an event is currently active."""
        event = await self.get_active_event()
        return event is not None and event.is_active

    async def can_send_invitations(self) -> bool:
        """
        Check if invitations can be sent.

        Returns True if:
        - An event exists
        - The event is active
        - Registration is open
        """
        event = await self.get_active_event()
        return (
            event is not None
            and event.is_active
            and getattr(event, 'registration_open', False)
        )

    async def get_active_event(self) -> Optional[Event]:
        """
        Get the currently active event.

        Returns the event marked as is_active=True, or None if no event is active.
        """
        result = await self.session.execute(
            select(Event)
            .where(Event.is_active == True)
            .order_by(Event.year.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_event(self, event_id: int) -> Optional[Event]:
        """Get an event by ID."""
        result = await self.session.execute(
            select(Event).where(Event.id == event_id)
        )
        return result.scalar_one_or_none()

    async def update_event(self, event_id: int, **kwargs) -> Optional[Event]:
        """
        Update an event with the provided fields.

        Args:
            event_id: ID of the event to update
            **kwargs: Fields to update (name, start_date, end_date, event_time,
                     event_location, is_active, vpn_available, test_mode, etc.)

        Returns:
            Updated event or None if not found
        """
        event = await self.get_event(event_id)
        if not event:
            return None

        # Update allowed fields
        for key, value in kwargs.items():
            if hasattr(event, key):
                setattr(event, key, value)

        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def list_events(self, include_archived: bool = False) -> List[Event]:
        """
        List all events.

        Args:
            include_archived: If True, include archived events. Default False.

        Returns:
            List of events ordered by year descending
        """
        query = select(Event).order_by(Event.year.desc())

        if not include_archived:
            query = query.where(Event.is_archived == False)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_event_by_year(self, year: int) -> Optional[Event]:
        """Get an event by year."""
        result = await self.session.execute(
            select(Event).where(Event.year == year)
        )
        return result.scalar_one_or_none()

    async def get_event_by_slug(self, slug: str) -> Optional[Event]:
        """Get an event by slug."""
        result = await self.session.execute(
            select(Event).where(Event.slug == slug)
        )
        return result.scalar_one_or_none()

    async def create_event(self, **kwargs) -> Event:
        """
        Create a new event.

        Args:
            **kwargs: Event fields (year, name, start_date, end_date, etc.)

        Returns:
            Created event
        """
        event = Event(**kwargs)
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def delete_event(self, event_id: int) -> bool:
        """
        Delete an event.

        Args:
            event_id: ID of the event to delete

        Returns:
            True if deleted, False if not found
        """
        event = await self.get_event(event_id)
        if not event:
            return False

        await self.session.delete(event)
        await self.session.commit()
        return True

    async def deactivate_other_events(self, except_event_id: int) -> None:
        """
        Deactivate all events except the specified one.

        Args:
            except_event_id: ID of the event to keep active
        """
        await self.session.execute(
            Event.__table__.update()
            .where(Event.id != except_event_id)
            .values(is_active=False)
        )

    async def get_event_statistics(self, event_id: int) -> dict:
        """
        Get participation statistics for an event.

        Args:
            event_id: ID of the event

        Returns:
            Dictionary with counts for each participation status:
            - total_invited: Total number of invited participants
            - total_confirmed: Number of confirmed participants
            - total_declined: Number of declined participants
            - total_no_response: Number of participants who haven't responded
        """
        # Count by status
        result = await self.session.execute(
            select(
                EventParticipation.status,
                func.count(EventParticipation.id).label('count')
            )
            .where(EventParticipation.event_id == event_id)
            .group_by(EventParticipation.status)
        )

        status_counts = {row.status: row.count for row in result.all()}

        return {
            "total_invited": sum(status_counts.values()),
            "total_confirmed": status_counts.get(ParticipationStatus.CONFIRMED.value, 0),
            "total_declined": status_counts.get(ParticipationStatus.DECLINED.value, 0),
            "total_no_response": status_counts.get(ParticipationStatus.NO_RESPONSE.value, 0)
        }
