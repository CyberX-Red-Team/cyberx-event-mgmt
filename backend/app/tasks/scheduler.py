"""Background job scheduler using APScheduler."""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

from app.config import get_settings


# Configure logging
logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Get the global scheduler instance, creating it if necessary."""
    global scheduler
    if scheduler is None:
        settings = get_settings()

        # Configure job stores and executors
        jobstores = {
            'default': MemoryJobStore()
        }
        executors = {
            'default': AsyncIOExecutor()
        }
        job_defaults = {
            'coalesce': True,  # Combine missed job runs into one
            'max_instances': 1,  # Only one instance of a job at a time
            'misfire_grace_time': 300  # 5 minutes grace period for misfired jobs
        }

        scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone='UTC'
        )

        logger.info("Scheduler created with UTC timezone")

    return scheduler


async def start_scheduler():
    """Start the scheduler and register all jobs."""
    from app.tasks.bulk_email import schedule_bulk_email_job
    from app.tasks.session_cleanup import schedule_session_cleanup_job
    from app.tasks.invitation_reminders import schedule_invitation_reminder_job
    from app.tasks.instance_status_sync import schedule_instance_status_sync_job
    from app.tasks.license_slot_reaper import schedule_license_slot_reaper_job
    from app.tasks.keycloak_sync import schedule_keycloak_sync_job

    sched = get_scheduler()

    if sched.running:
        logger.warning("Scheduler is already running")
        return

    # Register jobs
    schedule_bulk_email_job(sched)
    schedule_session_cleanup_job(sched)
    schedule_invitation_reminder_job(sched)
    schedule_instance_status_sync_job(sched)
    schedule_license_slot_reaper_job(sched)
    schedule_keycloak_sync_job(sched)

    # Register status heartbeat job (updates database every 60 seconds)
    sched.add_job(
        update_scheduler_status,
        'interval',
        seconds=60,
        id='scheduler_status_heartbeat',
        name='Scheduler Status Heartbeat',
        replace_existing=True
    )

    # Start the scheduler
    sched.start()
    logger.info("Scheduler started with %d jobs", len(sched.get_jobs()))

    # Update status immediately on startup
    await update_scheduler_status()

    # Log registered jobs
    for job in sched.get_jobs():
        logger.info("  - Job: %s, Next run: %s", job.id, job.next_run_time)


async def stop_scheduler():
    """Stop the scheduler gracefully."""
    global scheduler
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")
        scheduler = None


def list_jobs() -> list[dict]:
    """List all scheduled jobs and their status."""
    sched = get_scheduler()
    jobs = []
    for job in sched.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return jobs


async def update_scheduler_status():
    """Update scheduler status in database for web service to read."""
    from app.database import AsyncSessionLocal
    from app.models.scheduler_status import SchedulerStatus
    from sqlalchemy import select
    from datetime import datetime, timezone

    sched = get_scheduler()

    # Collect job information
    jobs = []
    for job in sched.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
        })

    # Update database
    async with AsyncSessionLocal() as session:
        try:
            # Try to get existing status record
            result = await session.execute(
                select(SchedulerStatus).where(SchedulerStatus.service_name == "web-service")
            )
            status = result.scalar_one_or_none()

            if status:
                # Update existing record
                status.is_running = sched.running
                status.jobs = jobs
                status.last_heartbeat = datetime.now(timezone.utc)
                status.updated_at = datetime.now(timezone.utc)
            else:
                # Create new record
                status = SchedulerStatus(
                    service_name="web-service",
                    is_running=sched.running,
                    jobs=jobs,
                    last_heartbeat=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(status)

            await session.commit()
            logger.debug(f"Updated scheduler status: running={sched.running}, jobs={len(jobs)}")
        except Exception as e:
            logger.error(f"Failed to update scheduler status: {e}")
            await session.rollback()


if __name__ == "__main__":
    """Entry point when running as a module."""
    import asyncio
    import signal
    import sys

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    async def main():
        """Main async function to start scheduler and keep it running."""
        logger.info("Starting background worker scheduler...")

        # Start the scheduler
        await start_scheduler()

        # Keep the process running
        try:
            logger.info("Scheduler is running. Press Ctrl+C to stop.")
            # Wait forever - scheduler runs in background
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("Received shutdown signal")
            await stop_scheduler()

    # Run the main async function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        sys.exit(0)
