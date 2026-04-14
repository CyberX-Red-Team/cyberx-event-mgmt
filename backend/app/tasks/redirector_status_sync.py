"""Redirector status sync background job.

Periodically SSH-tests every non-isolated redirector and updates its
connectivity status (online/offline/unknown). Mirrors the instance status
sync pattern but uses SSHService.run_test_connection instead of a cloud API.

Runs less frequently than instance sync (every 2 minutes) because each
check opens a real SSH connection and is considerably heavier than an
HTTP call to a cloud provider API.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import AsyncSessionLocal
from app.models.redirector import Redirector, RedirectorStatus
from app.services.redirector_service import RedirectorService
from app.services.event_service import EventService
from app.services.ssh_service import (
    SSHService,
    SSHConnectionError,
    SSHAuthError,
    SSHCommandError,
    NginxReloadError,
    run_test_connection,
)

logger = logging.getLogger(__name__)


async def _build_ssh(
    svc: RedirectorService, redirector: Redirector, session
) -> SSHService | None:
    """Decrypt credentials and build an SSHService for the redirector.

    Returns None when the redirector uses the infrastructure key but the
    active event has no key pair — the redirector can't be reached and
    its status cannot be determined, so we skip it.
    """
    if redirector.use_infrastructure_key:
        event_svc = EventService(session)
        event = await event_svc.get_active_event()
        if not event or not event.ssh_private_key:
            return None
        private_key_pem = event.ssh_private_key
        passphrase = None
    else:
        if not redirector.ssh_private_key:
            return None
        private_key_pem = svc.get_decrypted_key(redirector)
        passphrase = svc.get_decrypted_passphrase(redirector)

    return SSHService(
        hostname=redirector.current_ip,
        port=redirector.ssh_port,
        username=redirector.ssh_username,
        private_key_pem=private_key_pem,
        passphrase=passphrase,
    )


async def redirector_status_sync_job():
    """SSH-test every non-isolated redirector and update its status."""
    logger.info("Starting redirector status sync job...")
    start_time = datetime.now(timezone.utc)
    synced = 0
    errors = 0

    try:
        async with AsyncSessionLocal() as session:
            svc = RedirectorService(session)
            result = await session.execute(
                select(Redirector).where(
                    Redirector.status != RedirectorStatus.ISOLATED.value
                )
            )
            redirectors = list(result.scalars().all())

            if not redirectors:
                logger.debug("No redirectors to sync")
                return

            for redirector in redirectors:
                try:
                    ssh = await _build_ssh(svc, redirector, session)
                    if ssh is None:
                        continue

                    try:
                        check = await run_test_connection(ssh)
                        new_status = "online" if check.get("success") else "offline"
                        os_info = check.get("os_info")
                    except (SSHConnectionError, SSHAuthError,
                            SSHCommandError, NginxReloadError):
                        new_status = "offline"
                        os_info = None

                    if (
                        redirector.status != new_status
                        or redirector.last_tested_at is None
                        or os_info is not None
                    ):
                        await svc.update_status(
                            redirector, new_status, os_info=os_info
                        )
                        synced += 1

                except Exception as exc:
                    errors += 1
                    logger.error(
                        "Failed to sync redirector %s (%s): %s",
                        redirector.id, redirector.name, exc,
                    )

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "Redirector status sync completed: %d/%d updated, %d errors in %.2fs",
                synced, len(redirectors), errors, duration,
            )

    except Exception as exc:
        logger.error("Redirector status sync job failed: %s", exc)


def schedule_redirector_status_sync_job(scheduler: AsyncIOScheduler):
    """Register the redirector status sync job with the scheduler."""
    scheduler.add_job(
        redirector_status_sync_job,
        "interval",
        seconds=120,
        id="redirector_status_sync",
        name="Redirector Status Sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Scheduled redirector status sync job to run every 120 seconds")
