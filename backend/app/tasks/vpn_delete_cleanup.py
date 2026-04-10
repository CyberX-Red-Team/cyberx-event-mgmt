"""Daily cleanup of old VPN bulk-delete jobs."""
import logging

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.vpn_delete_service import VPNDeleteService

logger = logging.getLogger(__name__)


async def vpn_delete_cleanup_job():
    """Delete completed/failed VPN delete jobs older than the retention window."""
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        service = VPNDeleteService(session)
        deleted = await service.cleanup_old_jobs(settings.VPN_IMPORT_RETENTION_DAYS)
        if deleted:
            logger.info("VPN delete cleanup: deleted %d old job(s)", deleted)


def schedule_vpn_delete_cleanup_job(scheduler):
    """Register the cleanup job with APScheduler (daily)."""
    scheduler.add_job(
        func=vpn_delete_cleanup_job,
        trigger="interval",
        hours=24,
        id="vpn_delete_cleanup",
        name="VPN Delete Job Cleanup",
        replace_existing=True,
    )
    logger.info("Scheduled VPN delete cleanup job to run daily")
