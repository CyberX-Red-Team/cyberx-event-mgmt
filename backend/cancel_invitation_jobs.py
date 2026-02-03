"""Utility script to cancel all scheduled invitation email jobs."""
import asyncio
import sys
from pathlib import Path

# Add the backend directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.tasks.scheduler import get_scheduler


def cancel_all_invitation_jobs():
    """Cancel all scheduled invitation email jobs."""
    scheduler = get_scheduler()

    # Get all jobs
    all_jobs = scheduler.get_jobs()

    print(f"\n=== Current Scheduled Jobs ===")
    print(f"Total jobs: {len(all_jobs)}\n")

    for job in all_jobs:
        print(f"Job ID: {job.id}")
        print(f"  Name: {job.name}")
        print(f"  Next run: {job.next_run_time}")
        print(f"  Trigger: {job.trigger}")
        print()

    # Find invitation email jobs
    invitation_jobs = [job for job in all_jobs if "invitation_emails_event_" in job.id]

    if not invitation_jobs:
        print("No invitation email jobs found.")
        return

    print(f"\n=== Found {len(invitation_jobs)} Invitation Email Job(s) ===")
    for job in invitation_jobs:
        print(f"  - {job.id} (next run: {job.next_run_time})")

    # Ask for confirmation
    response = input("\nCancel all invitation email jobs? (yes/no): ").strip().lower()

    if response == "yes":
        for job in invitation_jobs:
            scheduler.remove_job(job.id)
            print(f"✓ Cancelled: {job.id}")
        print(f"\n✓ Successfully cancelled {len(invitation_jobs)} job(s)")
    else:
        print("Cancelled. No jobs were removed.")


if __name__ == "__main__":
    try:
        cancel_all_invitation_jobs()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
