"""Daily cleanup of old VPN import jobs."""
import logging

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.vpn_import_service import VPNImportService

logger = logging.getLogger(__name__)


async def vpn_import_cleanup_job():
    """Delete completed/failed VPN import jobs older than the retention window."""
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        service = VPNImportService(session)
        deleted = await service.cleanup_old_jobs(settings.VPN_IMPORT_RETENTION_DAYS)
        if deleted:
            logger.info("VPN import cleanup: deleted %d old job(s)", deleted)


def schedule_vpn_import_cleanup_job(scheduler):
    """Register the cleanup job with APScheduler (daily)."""
    scheduler.add_job(
        func=vpn_import_cleanup_job,
        trigger="interval",
        hours=24,
        id="vpn_import_cleanup",
        name="VPN Import Job Cleanup",
        replace_existing=True,
    )
    logger.info("Scheduled VPN import cleanup job to run daily")
