"""Event-based batch email processor - processes queued emails in batches."""
import logging
from datetime import datetime, timezone
from sqlalchemy import select, and_
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.email_queue_service import EmailQueueService


logger = logging.getLogger(__name__)
settings = get_settings()


async def discover_and_queue_emails():
    """
    Discovery job: Find users who need password emails and add them to the queue.

    This replaces the old polling approach with an event-based queue.
    Runs less frequently since the queue is populated by events.

    Eligible users are those who:
    - confirmed = 'YES'
    - password_email_sent IS NULL
    - email_status NOT IN ('BOUNCED', 'SPAM_REPORTED', 'UNSUBSCRIBED')
    - is_active = True
    """
    logger.info("Starting email discovery job...")
    start_time = datetime.now(timezone.utc)

    try:
        async with AsyncSessionLocal() as session:
            # Query eligible users (allow GOOD and UNKNOWN, block BOUNCED/SPAM/UNSUBSCRIBED)
            result = await session.execute(
                select(User).where(
                    and_(
                        User.confirmed == 'YES',
                        User.password_email_sent.is_(None),
                        User.email_status.notin_(['BOUNCED', 'SPAM_REPORTED', 'UNSUBSCRIBED']),
                        User.is_active == True
                    )
                ).order_by(User.created_at.asc())
                .limit(100)  # Discover up to 100 users at a time
            )
            eligible_users = list(result.scalars().all())

            if not eligible_users:
                logger.info("No eligible users found for password email")
                return

            logger.info("Found %d eligible users to queue for password email", len(eligible_users))

            # Trigger workflows for eligible users
            from app.services.workflow_service import WorkflowService
            from app.models.email_workflow import WorkflowTriggerEvent

            workflow_service = WorkflowService(session)
            queued_count = 0

            for user in eligible_users:
                try:
                    # Trigger user_created workflow (discovery fallback)
                    triggered = await workflow_service.trigger_workflow(
                        trigger_event=WorkflowTriggerEvent.USER_CREATED,
                        user_id=user.id,
                        custom_vars={
                            "login_url": "https://portal.cyberxredteam.org/login"
                        }
                    )
                    if triggered > 0:
                        queued_count += triggered
                except Exception as e:
                    logger.error(f"Failed to trigger workflows for user {user.id}: {str(e)}")

            # Log summary
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "Email discovery completed: %d users queued in %.2f seconds",
                queued_count, duration
            )

    except Exception as e:
        logger.error("Email discovery job failed: %s", str(e))
        raise


async def process_email_batch():
    """
    Process pending emails from the queue in batches.

    This is the event-driven replacement for the old bulk email job.
    Processes whatever is in the queue rather than polling the database.
    """
    logger.info("Starting batch email processor...")
    start_time = datetime.now(timezone.utc)

    try:
        async with AsyncSessionLocal() as session:
            queue_service = EmailQueueService(session)

            # Process batch
            batch_log = await queue_service.process_batch(
                batch_size=50,  # SendGrid rate limit friendly
                worker_id=f"scheduled_worker_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            )

            # Log summary
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.info(
                "Batch processor completed: %d sent, %d failed in %.2f seconds (batch_id: %s)",
                batch_log.total_sent,
                batch_log.total_failed,
                duration,
                batch_log.batch_id
            )

    except Exception as e:
        logger.error("Batch email processor failed: %s", str(e))
        raise


def schedule_bulk_email_job(scheduler: AsyncIOScheduler):
    """
    Register the event-based email jobs with the scheduler.

    Two jobs:
    1. Discovery: Finds eligible users and adds to queue (runs less frequently)
    2. Batch Processor: Processes queued emails (runs more frequently)
    """
    # Discovery job - runs every 2 hours to catch any missed events
    # In a pure event-based system, this could be removed once all events are captured
    scheduler.add_job(
        discover_and_queue_emails,
        'interval',
        hours=2,
        id='email_discovery',
        name='Email Discovery (Queue Population)',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # Batch processor - runs every 15 minutes to process the queue
    # More frequent than discovery since it processes event-triggered items
    scheduler.add_job(
        process_email_batch,
        'interval',
        minutes=15,
        id='email_batch_processor',
        name='Email Batch Processor',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    logger.info("Scheduled event-based email jobs:")
    logger.info("  - Discovery: every 2 hours (fallback for missed events)")
    logger.info("  - Batch Processor: every 15 minutes (process queue)")
