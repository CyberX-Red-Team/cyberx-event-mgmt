"""License slot reaper background job - cleans up expired install slots."""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import AsyncSessionLocal
from app.services.license_service import LicenseService


logger = logging.getLogger(__name__)


async def license_slot_reaper_job():
    """
    Clean up license slots that exceeded their product's TTL.

    Marks expired active slots as released with result="expired".
    """
    logger.debug("Starting license slot reaper job...")
    start_time = datetime.now(timezone.utc)

    try:
        async with AsyncSessionLocal() as session:
            service = LicenseService(session)
            reaped = await service.reap_expired_slots()

            if reaped > 0:
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                logger.info(
                    "License slot reaper completed: %d slots reaped in %.2fs",
                    reaped, duration
                )

    except Exception as e:
        logger.error("License slot reaper job failed: %s", e)


def schedule_license_slot_reaper_job(scheduler: AsyncIOScheduler):
    """Register the license slot reaper job with the scheduler."""
    scheduler.add_job(
        license_slot_reaper_job,
        'interval',
        seconds=60,
        id='license_slot_reaper',
        name='License Slot Reaper',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    logger.info("Scheduled license slot reaper job to run every 60 seconds")
