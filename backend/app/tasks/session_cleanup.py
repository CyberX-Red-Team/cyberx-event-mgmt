"""Session cleanup background job - removes expired sessions."""
import logging
from datetime import datetime, timezone
from sqlalchemy import delete, select, func
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import AsyncSessionLocal
from app.models.session import Session


logger = logging.getLogger(__name__)


async def session_cleanup_job():
    """
    Clean up expired sessions from the database.

    Removes all sessions where:
    - expires_at < current time
    - OR is_active = False
    """
    logger.info("Starting session cleanup job...")
    start_time = datetime.now(timezone.utc)

    try:
        async with AsyncSessionLocal() as session:
            # Count expired sessions first
            count_result = await session.execute(
                select(func.count(Session.id)).where(
                    (Session.expires_at < datetime.now(timezone.utc)) |
                    (Session.is_active == False)
                )
            )
            expired_count = count_result.scalar() or 0

            if expired_count == 0:
                logger.info("No expired sessions to clean up")
                return

            # Delete expired sessions
            delete_result = await session.execute(
                delete(Session).where(
                    (Session.expires_at < datetime.now(timezone.utc)) |
                    (Session.is_active == False)
                )
            )
            await session.commit()

            # Log result
            deleted_count = delete_result.rowcount
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "Session cleanup completed: %d sessions deleted in %.2f seconds",
                deleted_count, duration
            )

    except Exception as e:
        logger.error("Session cleanup job failed: %s", str(e))
        raise


def schedule_session_cleanup_job(scheduler: AsyncIOScheduler):
    """Register the session cleanup job with the scheduler."""
    # Run every hour
    scheduler.add_job(
        session_cleanup_job,
        'interval',
        hours=1,
        id='session_cleanup',
        name='Session Cleanup',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    logger.info("Scheduled session cleanup job to run every hour")
