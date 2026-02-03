#!/usr/bin/env python3
"""Test script for background job scheduler."""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tasks import (
    get_scheduler,
    start_scheduler,
    stop_scheduler,
    list_jobs,
    bulk_password_email_job,
    session_cleanup_job,
)


async def test_scheduler():
    """Test the scheduler and background jobs."""
    print("=" * 60)
    print("Testing Background Job Scheduler")
    print("=" * 60)

    # Test 1: Start the scheduler
    print("\n1. Starting scheduler...")
    try:
        await start_scheduler()
        print("   Scheduler started successfully")
    except Exception as e:
        print(f"   FAILED: {e}")
        return

    # Test 2: List registered jobs
    print("\n2. Listing registered jobs...")
    jobs = list_jobs()
    print(f"   Found {len(jobs)} jobs:")
    for job in jobs:
        print(f"   - {job['id']}: {job['name']}")
        print(f"     Trigger: {job['trigger']}")
        print(f"     Next run: {job['next_run_time']}")

    # Test 3: Verify expected jobs are registered
    print("\n3. Verifying expected jobs...")
    expected_jobs = ['bulk_password_email', 'session_cleanup']
    job_ids = [job['id'] for job in jobs]
    for expected in expected_jobs:
        if expected in job_ids:
            print(f"   {expected}: REGISTERED")
        else:
            print(f"   {expected}: MISSING")

    # Test 4: Test session cleanup job manually (safe to run)
    print("\n4. Testing session cleanup job...")
    try:
        await session_cleanup_job()
        print("   Session cleanup job completed successfully")
    except Exception as e:
        print(f"   Session cleanup job error (expected if no database): {e}")

    # Test 5: Stop the scheduler
    print("\n5. Stopping scheduler...")
    await stop_scheduler()
    print("   Scheduler stopped successfully")

    print("\n" + "=" * 60)
    print("Scheduler tests completed!")
    print("=" * 60)


async def test_bulk_email_dry_run():
    """
    Dry run test for bulk email job.
    This will query eligible users but not actually send emails.
    """
    print("\n" + "=" * 60)
    print("Bulk Email Job - Dry Run Query")
    print("=" * 60)

    try:
        from sqlalchemy import select, and_, func
        from app.database import AsyncSessionLocal
        from app.models.user import User

        async with AsyncSessionLocal() as session:
            # Count eligible users
            result = await session.execute(
                select(func.count(User.id)).where(
                    and_(
                        User.confirmed == 'YES',
                        User.password_email_sent.is_(None),
                        User.email_status == 'GOOD',
                        User.is_active == True
                    )
                )
            )
            eligible_count = result.scalar() or 0

            # Get first 5 eligible users for preview
            result = await session.execute(
                select(User).where(
                    and_(
                        User.confirmed == 'YES',
                        User.password_email_sent.is_(None),
                        User.email_status == 'GOOD',
                        User.is_active == True
                    )
                ).limit(5)
            )
            sample_users = list(result.scalars().all())

            print(f"\nEligible users for password email: {eligible_count}")
            if sample_users:
                print("\nSample of eligible users:")
                for user in sample_users:
                    print(f"  - {user.first_name} {user.last_name} ({user.email})")
            else:
                print("\n  No eligible users found")

    except Exception as e:
        print(f"\nError querying database: {e}")
        print("(This is expected if the database is not running)")


if __name__ == "__main__":
    print("CyberX Background Jobs Test Suite")
    print("=================================\n")

    # Run scheduler tests
    asyncio.run(test_scheduler())

    # Run dry run email query
    asyncio.run(test_bulk_email_dry_run())
