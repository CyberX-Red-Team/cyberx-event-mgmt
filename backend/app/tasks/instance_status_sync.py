"""Instance status sync background job - polls cloud providers for BUILDING instances."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import AsyncSessionLocal
from app.models.instance import Instance
from app.services.cloud_provider_factory import CloudProviderFactory
from app.config import get_settings


logger = logging.getLogger(__name__)


async def instance_status_sync_job():
    """
    Poll cloud providers for status of all non-terminal instances.

    Syncs status and IP address for instances in BUILDING state.
    Works with both OpenStack and DigitalOcean providers.
    """
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
                    Instance.provider_instance_id.isnot(None),
                )
            )
            building_instances = list(result.scalars().all())

            if not building_instances:
                logger.debug("No BUILDING instances to sync")
                return

            for instance in building_instances:
                try:
                    # Get appropriate provider service
                    provider_service = CloudProviderFactory.get_provider(
                        instance.provider, session
                    )

                    # Get status from provider
                    provider_data = await provider_service.get_instance_status(
                        instance.provider_instance_id
                    )

                    if provider_data:
                        # Update status
                        new_status = provider_service.normalize_status(
                            provider_data.get("status", "")
                        )
                        instance.status = new_status

                        # Update IP if available
                        ip_address = provider_service.extract_ip_address(provider_data)
                        if ip_address:
                            instance.ip_address = ip_address

                        await session.commit()

                        if new_status != "BUILDING":
                            synced += 1
                            logger.info(
                                "Synced instance %d (%s) - %s → %s",
                                instance.id, instance.name, "BUILDING", new_status
                            )

                except Exception as e:
                    errors += 1
                    logger.error(
                        "Failed to sync instance %d (%s, provider=%s): %s",
                        instance.id, instance.name, instance.provider, e
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
