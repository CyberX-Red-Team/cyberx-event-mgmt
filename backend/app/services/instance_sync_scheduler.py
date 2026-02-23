"""Background scheduler for periodic instance status synchronization."""
import logging
import asyncio
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.models.instance import Instance
from app.services.instance_service import InstanceService
from app.config import get_settings

logger = logging.getLogger(__name__)


class InstanceSyncScheduler:
    """Scheduler for background instance status synchronization."""

    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.session_maker: Optional[async_sessionmaker] = None
        self._sync_failures = 0
        self._total_syncs = 0
        self._last_sync_start: Optional[datetime] = None
        self._last_sync_end: Optional[datetime] = None

    def initialize(self):
        """Initialize the scheduler with database connection."""
        settings = get_settings()

        # Create async engine for background tasks
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
        )
        self.session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

        # Initialize APScheduler
        self.scheduler = AsyncIOScheduler()

        # Schedule instance sync every 2 minutes
        self.scheduler.add_job(
            self._sync_all_instances,
            IntervalTrigger(minutes=2),
            id="instance_status_sync",
            name="Sync all instance statuses from cloud providers",
            replace_existing=True,
            max_instances=1,  # Prevent overlapping runs
        )

        logger.info("Initialized instance sync scheduler (interval: 2 minutes)")

    def start(self):
        """Start the scheduler."""
        if not self.scheduler:
            raise RuntimeError("Scheduler not initialized. Call initialize() first.")

        self.scheduler.start()
        logger.info("Started instance sync scheduler")

    def shutdown(self):
        """Shutdown the scheduler gracefully."""
        if self.scheduler:
            self.scheduler.shutdown(wait=True)
            logger.info("Shutdown instance sync scheduler")

    async def _sync_all_instances(self):
        """Sync status for all active instances from their cloud providers."""
        self._last_sync_start = datetime.utcnow()
        sync_count = 0
        failure_count = 0

        logger.info("Starting scheduled instance status sync")

        try:
            async with self.session_maker() as session:
                # Fetch all non-deleted instances
                result = await session.execute(
                    select(Instance).where(Instance.deleted_at.is_(None))
                )
                instances = result.scalars().all()

                logger.info("Found %d instances to sync", len(instances))

                # Create instance service
                instance_service = InstanceService(session)

                # Sync each instance
                for instance in instances:
                    if not instance.provider_instance_id:
                        # Skip instances without provider IDs (not yet created)
                        continue

                    try:
                        await instance_service.sync_instance_status(instance.id)
                        sync_count += 1
                    except Exception as e:
                        failure_count += 1
                        logger.error(
                            "Failed to sync instance %d (%s, provider=%s): %s",
                            instance.id,
                            instance.name,
                            instance.provider,
                            e
                        )

        except Exception as e:
            logger.error("Error during scheduled instance sync: %s", e)
            failure_count += 1

        # Update stats
        self._total_syncs += sync_count
        self._sync_failures += failure_count
        self._last_sync_end = datetime.utcnow()

        duration = (self._last_sync_end - self._last_sync_start).total_seconds()

        logger.info(
            "Completed scheduled instance sync: %d synced, %d failures, %.2f seconds (total: %d syncs, %d failures)",
            sync_count,
            failure_count,
            duration,
            self._total_syncs,
            self._sync_failures
        )

    def get_stats(self) -> dict:
        """Get sync statistics."""
        return {
            "total_syncs": self._total_syncs,
            "total_failures": self._sync_failures,
            "last_sync_start": self._last_sync_start.isoformat() if self._last_sync_start else None,
            "last_sync_end": self._last_sync_end.isoformat() if self._last_sync_end else None,
        }


# Global scheduler instance
_scheduler: Optional[InstanceSyncScheduler] = None


def get_scheduler() -> InstanceSyncScheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = InstanceSyncScheduler()
    return _scheduler
