"""Instance status sync background job - polls OpenStack for BUILDING instances."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import AsyncSessionLocal
from app.models.instance import Instance
from app.services.openstack_service import OpenStackService
from app.config import get_settings


logger = logging.getLogger(__name__)


async def instance_status_sync_job():
    """
    Poll OpenStack for status of all non-terminal instances.

    Syncs status and IP address for instances in BUILDING state.
    Skips if OpenStack is not configured.
    """
    settings = get_settings()
    if not settings.OS_AUTH_URL:
        return  # OpenStack not configured, skip silently

    logger.info("Starting instance status sync job...")
    start_time = datetime.now(timezone.utc)
    synced = 0
    errors = 0

    try:
        async with AsyncSessionLocal() as session:
            # Find all BUILDING instances that haven't been soft-deleted
            result = await session.execute(
                select(Instance).where(
                    Instance.status == "BUILDING",
                    Instance.deleted_at.is_(None),
                    Instance.openstack_id.isnot(None),
                )
            )
            building_instances = list(result.scalars().all())

            if not building_instances:
                logger.debug("No BUILDING instances to sync")
                return

            service = OpenStackService(session)

            for instance in building_instances:
                try:
                    updated = await service.sync_instance_status(instance.id)
                    if updated and updated.status != "BUILDING":
                        synced += 1
                except Exception as e:
                    errors += 1
                    logger.error(
                        "Failed to sync instance %d (%s): %s",
                        instance.id, instance.name, e
                    )

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "Instance status sync completed: %d/%d synced, %d errors in %.2fs",
                synced, len(building_instances), errors, duration
            )

    except Exception as e:
        logger.error("Instance status sync job failed: %s", e)


def schedule_instance_status_sync_job(scheduler: AsyncIOScheduler):
    """Register the instance status sync job with the scheduler."""
    scheduler.add_job(
        instance_status_sync_job,
        'interval',
        seconds=30,
        id='instance_status_sync',
        name='Instance Status Sync',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    logger.info("Scheduled instance status sync job to run every 30 seconds")
