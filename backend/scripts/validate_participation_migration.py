"""
Validate that user.confirmed matches EventParticipation.status for current event.

This script checks data consistency after the migration to EventParticipation-based
confirmation tracking. Run this to verify that the legacy user.confirmed field
matches the current event's EventParticipation.status.

Usage:
    python -m scripts.validate_participation_migration
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.event import Event, EventParticipation, ParticipationStatus
from sqlalchemy import select


async def validate_migration():
    """Check consistency between user.confirmed and EventParticipation.status."""
    print("=" * 80)
    print("EventParticipation Migration Validation")
    print("=" * 80)
    print()

    async with AsyncSessionLocal() as session:
        # Get current active event
        result = await session.execute(
            select(Event).where(Event.is_active == True).limit(1)
        )
        current_event = result.scalar_one_or_none()

        if not current_event:
            print("❌ No active event found")
            print("   Cannot validate without an active event")
            return False

        print(f"✓ Active Event: {current_event.name} (ID: {current_event.id})")
        print()

        # Get all users with EventParticipation for current event
        result = await session.execute(
            select(User, EventParticipation)
            .join(EventParticipation, EventParticipation.user_id == User.id)
            .where(EventParticipation.event_id == current_event.id)
        )

        users_with_participation = list(result.all())

        if not users_with_participation:
            print("⚠️  No users with EventParticipation records found")
            print("   This is normal for new events before invitations are sent")
            return True

        print(f"Checking {len(users_with_participation)} users with EventParticipation records...")
        print()

        # Define expected mappings
        status_map = {
            ParticipationStatus.CONFIRMED.value: 'YES',
            ParticipationStatus.DECLINED.value: 'NO',
            ParticipationStatus.INVITED.value: 'UNKNOWN',
            ParticipationStatus.NO_RESPONSE.value: 'UNKNOWN'
        }

        inconsistencies = []
        for user, participation in users_with_participation:
            expected_confirmed = status_map.get(participation.status)

            if user.confirmed != expected_confirmed:
                inconsistencies.append({
                    'user_id': user.id,
                    'email': user.email,
                    'user_confirmed': user.confirmed,
                    'participation_status': participation.status,
                    'expected': expected_confirmed,
                    'participation_id': participation.id
                })

        # Print results
        if not inconsistencies:
            print("✅ All users consistent!")
            print(f"   {len(users_with_participation)} users checked, 0 inconsistencies found")
            print()
            return True

        print(f"❌ Found {len(inconsistencies)} inconsistencies:")
        print()

        for item in inconsistencies:
            print(f"User {item['user_id']} ({item['email']}):")
            print(f"  user.confirmed = '{item['user_confirmed']}'")
            print(f"  EventParticipation.status = '{item['participation_status']}'")
            print(f"  Expected user.confirmed = '{item['expected']}'")
            print(f"  EventParticipation ID: {item['participation_id']}")
            print()

        print("=" * 80)
        print("Summary:")
        print(f"  Total users: {len(users_with_participation)}")
        print(f"  Consistent: {len(users_with_participation) - len(inconsistencies)}")
        print(f"  Inconsistent: {len(inconsistencies)}")
        print("=" * 80)
        print()

        return False


async def check_users_without_participation():
    """Check for active users who should have EventParticipation but don't."""
    print("Checking for users without EventParticipation records...")
    print()

    async with AsyncSessionLocal() as session:
        # Get current active event
        result = await session.execute(
            select(Event).where(Event.is_active == True).limit(1)
        )
        current_event = result.scalar_one_or_none()

        if not current_event:
            return

        # Find active invitees/sponsors without EventParticipation
        result = await session.execute(
            select(User)
            .outerjoin(EventParticipation, EventParticipation.user_id == User.id)
            .where(User.role.in_(['invitee', 'sponsor']))
            .where(User.is_active == True)
            .where(EventParticipation.id.is_(None))
        )

        users_without_participation = list(result.scalars().all())

        if not users_without_participation:
            print("✅ All active invitees/sponsors have EventParticipation records")
            print()
            return

        print(f"⚠️  Found {len(users_without_participation)} active users without EventParticipation:")
        print()

        for user in users_without_participation[:10]:  # Show first 10
            print(f"  - {user.email} (ID: {user.id}, confirmed: {user.confirmed})")

        if len(users_without_participation) > 10:
            print(f"  ... and {len(users_without_participation) - 10} more")

        print()
        print("These users will be included in the next invitation batch.")
        print()


async def main():
    """Run all validation checks."""
    try:
        # Check consistency for users with EventParticipation
        consistent = await validate_migration()

        # Check for users without EventParticipation
        await check_users_without_participation()

        # Exit with appropriate code
        sys.exit(0 if consistent else 1)

    except Exception as e:
        print(f"❌ Error during validation: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
