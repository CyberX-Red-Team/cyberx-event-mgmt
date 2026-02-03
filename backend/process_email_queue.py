"""Manually process the email queue to send pending emails."""
import asyncio
import logging
from datetime import datetime, timezone
from app.database import AsyncSessionLocal
from app.services.email_queue_service import EmailQueueService


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Manually process email queue."""
    logger.info("Starting manual email queue processing...")
    start_time = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        queue_service = EmailQueueService(session)

        # Get queue stats before processing
        stats_before = await queue_service.get_queue_stats()
        logger.info("Queue stats before processing:")
        for status, count in stats_before.items():
            if count > 0:
                logger.info(f"  {status}: {count}")

        # Process the batch
        batch_log = await queue_service.process_batch(
            batch_size=50,
            worker_id=f"manual_worker_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        )

        # Get queue stats after processing
        stats_after = await queue_service.get_queue_stats()
        logger.info("\nQueue stats after processing:")
        for status, count in stats_after.items():
            if count > 0:
                logger.info(f"  {status}: {count}")

        # Log summary
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"\n=== Processing Complete ===")
        logger.info(f"Batch ID: {batch_log.batch_id}")
        logger.info(f"Total processed: {batch_log.total_processed}")
        logger.info(f"Successfully sent: {batch_log.total_sent}")
        logger.info(f"Failed: {batch_log.total_failed}")
        logger.info(f"Duration: {duration:.2f} seconds")

        if batch_log.total_sent > 0:
            logger.info(f"\n✓ {batch_log.total_sent} email(s) sent successfully!")

        if batch_log.total_failed > 0:
            logger.warning(f"\n✗ {batch_log.total_failed} email(s) failed to send")


if __name__ == "__main__":
    asyncio.run(main())
