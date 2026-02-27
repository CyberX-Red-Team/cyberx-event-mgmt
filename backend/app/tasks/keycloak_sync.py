"""Background job for syncing credentials to Keycloak."""
import logging

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.keycloak_sync_service import KeycloakSyncService

logger = logging.getLogger(__name__)


async def keycloak_sync_job():
    """
    Process pending Keycloak sync queue entries.

    Runs periodically to push queued credential changes (create, update,
    delete) to Keycloak when it is available. Skips processing entirely
    if PASSWORD_SYNC_ENABLED is False.
    """
    settings = get_settings()

    if not settings.PASSWORD_SYNC_ENABLED:
        logger.debug("Keycloak sync is disabled (PASSWORD_SYNC_ENABLED=False)")
        return

    if not settings.KEYCLOAK_URL:
        logger.debug("Keycloak sync skipped: KEYCLOAK_URL not configured")
        return

    async with AsyncSessionLocal() as session:
        try:
            service = KeycloakSyncService(session)
            result = await service.process_sync_queue()

            if result["synced"] > 0:
                logger.info(f"Keycloak sync: {result['synced']} credentials synced")
            if result["failed"] > 0:
                logger.warning(
                    f"Keycloak sync: {result['failed']} credentials failed, will retry"
                )
            if result["skipped"] > 0:
                logger.info(
                    f"Keycloak sync: {result['skipped']} entries skipped "
                    f"(Keycloak unavailable)"
                )

        except Exception as e:
            logger.error(f"Keycloak sync job error: {e}", exc_info=True)


def schedule_keycloak_sync_job(scheduler):
    """
    Register the Keycloak sync job with APScheduler.

    Args:
        scheduler: APScheduler instance
    """
    settings = get_settings()
    interval_minutes = settings.PASSWORD_SYNC_INTERVAL_MINUTES

    scheduler.add_job(
        func=keycloak_sync_job,
        trigger='interval',
        minutes=interval_minutes,
        id='keycloak_sync',
        name='Keycloak Credential Sync',
        replace_existing=True
    )

    logger.info(
        f"Scheduled Keycloak sync job to run every {interval_minutes} minutes"
    )
