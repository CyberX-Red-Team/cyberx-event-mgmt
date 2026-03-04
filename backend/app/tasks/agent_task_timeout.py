"""Background job for timing out stale agent tasks."""
import logging

from app.database import AsyncSessionLocal
from app.services.agent_service import AgentService

logger = logging.getLogger(__name__)


async def agent_task_timeout_job():
    """Mark stale IN_PROGRESS agent tasks as FAILED."""
    async with AsyncSessionLocal() as session:
        try:
            service = AgentService(session)
            count = await service.timeout_stale_tasks()
            if count > 0:
                logger.info("Agent task timeout: %d tasks timed out", count)
        except Exception as e:
            logger.error("Agent task timeout job error: %s", e, exc_info=True)


def schedule_agent_task_timeout_job(scheduler):
    """Register the agent task timeout job with APScheduler."""
    scheduler.add_job(
        func=agent_task_timeout_job,
        trigger='interval',
        minutes=5,
        id='agent_task_timeout',
        name='Agent Task Timeout',
        replace_existing=True,
    )
    logger.info("Scheduled agent task timeout job to run every 5 minutes")
