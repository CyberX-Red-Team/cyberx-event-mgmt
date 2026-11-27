"""Daily data-retention job (see app.services.retention_service)."""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.audit_service import AuditService
from app.services.retention_service import RUN_ACTION, RetentionService

logger = logging.getLogger(__name__)


async def run_retention(session, dry_run: bool) -> dict:
    """Run every rule and record one audit entry holding counts only."""
    results = await RetentionService(session).run_all(dry_run=dry_run)
    await AuditService(session).log(
        action=RUN_ACTION,
        resource_type="SYSTEM",
        details=results,
    )
    return results


async def data_retention_job():
    """Scheduled entry point. RETENTION_ENABLED=false means a dry run (counts only)."""
    dry_run = not get_settings().RETENTION_ENABLED
    async with AsyncSessionLocal() as session:
        try:
            results = await run_retention(session, dry_run=dry_run)
            logger.info("Data retention %s: %s", "dry run" if dry_run else "run", results)
        except Exception:
            logger.exception("Data retention job failed")
            raise


def schedule_data_retention_job(scheduler: AsyncIOScheduler):
    hour = get_settings().RETENTION_JOB_HOUR_UTC
    scheduler.add_job(
        data_retention_job,
        "cron",
        hour=hour,
        minute=30,
        id="data_retention",
        name="Data Retention",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Scheduled data retention job daily at %02d:30 UTC", hour)
