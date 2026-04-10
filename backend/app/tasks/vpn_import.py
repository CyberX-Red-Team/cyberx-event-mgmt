"""Background job that processes pending VPN import jobs."""
import logging

from app.database import AsyncSessionLocal
from app.services.vpn_import_service import VPNImportService

logger = logging.getLogger(__name__)


# Number of jobs to process per scheduler tick. Normally there's at most one,
# but loop a few times to drain a small backlog without waiting another tick.
MAX_JOBS_PER_TICK = 5


async def vpn_import_job():
    """
    Pick up pending VPN import jobs and process them cooperatively.

    Runs in the same event loop as the FastAPI app, so each call to
    ``process_job`` is responsible for yielding (via ``await asyncio.sleep(0)``
    between chunks) so HTTP requests can still be served.
    """
    async with AsyncSessionLocal() as session:
        service = VPNImportService(session)
        for _ in range(MAX_JOBS_PER_TICK):
            job = await service.claim_next_pending_job()
            if job is None:
                return
            try:
                await service.process_job(job)
            except Exception:
                logger.exception("Unhandled error in VPN import job %s", job.id)
                # Continue to next pending job; the failed one is already
                # marked as failed by process_job's own except block.


def schedule_vpn_import_job(scheduler):
    """Register the VPN import job with APScheduler (every 30 seconds)."""
    scheduler.add_job(
        func=vpn_import_job,
        trigger="interval",
        seconds=30,
        id="vpn_import",
        name="VPN Import Job Processor",
        replace_existing=True,
    )
    logger.info("Scheduled VPN import job to run every 30 seconds")
