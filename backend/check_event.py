"""Quick diagnostic script to check event status in database."""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models.event import Event


async def check_events():
    """Check what events exist and their status."""
    # Get DATABASE_URL from environment
    import os
    database_url = os.getenv('DATABASE_URL')

    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    # Convert to async URL if needed
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    print(f"Connecting to database...")
    print(f"URL (masked): {database_url.split('@')[1] if '@' in database_url else 'localhost'}\n")

    # Create engine
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get all events
        result = await session.execute(select(Event).order_by(Event.year.desc()))
        events = result.scalars().all()

        if not events:
            print("❌ NO EVENTS FOUND IN DATABASE")
            return

        print(f"Found {len(events)} event(s):\n")
        print("=" * 80)

        for event in events:
            print(f"ID: {event.id}")
            print(f"Year: {event.year}")
            print(f"Name: {event.name}")
            print(f"is_active: {event.is_active} {'✅' if event.is_active else '❌'}")
            print(f"registration_open: {event.registration_open}")
            print(f"test_mode: {getattr(event, 'test_mode', False)}")
            print(f"vpn_available: {getattr(event, 'vpn_available', False)}")
            print(f"Start Date: {event.start_date}")
            print(f"End Date: {event.end_date}")
            print(f"Event Time: {event.event_time}")
            print(f"Event Location: {event.event_location}")
            print(f"Terms Version: {event.terms_version}")
            print("=" * 80)

        # Check for active event
        active_result = await session.execute(
            select(Event).where(Event.is_active == True).order_by(Event.year.desc()).limit(1)
        )
        active_event = active_result.scalar_one_or_none()

        print("\n")
        if active_event:
            print(f"✅ ACTIVE EVENT FOUND: {active_event.name} ({active_event.year})")
        else:
            print("❌ NO ACTIVE EVENT FOUND")
            print("   To fix: Update an event with is_active=True")

    await engine.dispose()


if __name__ == "__main__":
    print("\n🔍 Event Status Diagnostic Tool\n")
    asyncio.run(check_events())
