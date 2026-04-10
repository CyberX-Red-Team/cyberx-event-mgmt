"""Background job that processes pending VPN bulk-delete jobs."""
import logging

from app.database import AsyncSessionLocal
from app.services.vpn_delete_service import VPNDeleteService

logger = logging.getLogger(__name__)


# Drain a small backlog per tick rather than waiting another 30s for the
# next pending job.
MAX_JOBS_PER_TICK = 5


async def vpn_delete_job():
    """
    Pick up pending VPN bulk-delete jobs and process them cooperatively.

    Runs in the same event loop as the FastAPI app, so each chunk of work
    yields back via ``await asyncio.sleep(0)`` so HTTP requests can still
    be served while a large delete runs.
    """
    async with AsyncSessionLocal() as session:
        service = VPNDeleteService(session)
        for _ in range(MAX_JOBS_PER_TICK):
            job = await service.claim_next_pending_job()
            if job is None:
                return
            try:
                await service.process_job(job)
            except Exception:
                logger.exception("Unhandled error in VPN delete job %s", job.id)
                # Continue draining; the failed job is already marked failed
                # by process_job's own except block.


def schedule_vpn_delete_job(scheduler):
    """Register the VPN delete job with APScheduler (every 30 seconds)."""
    scheduler.add_job(
        func=vpn_delete_job,
        trigger="interval",
        seconds=30,
        id="vpn_delete",
        name="VPN Bulk Delete Job Processor",
        replace_existing=True,
    )
    logger.info("Scheduled VPN delete job to run every 30 seconds")
