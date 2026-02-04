#!/usr/bin/env python3
"""Entry point for running the background scheduler worker."""
import asyncio
import logging
import sys

from app.tasks.scheduler import start_scheduler, stop_scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Main async function to start scheduler and keep it running."""
    logger.info("Starting background worker scheduler...")

    # Start the scheduler
    await start_scheduler()

    # Keep the process running
    try:
        logger.info("Scheduler is running. Press Ctrl+C to stop.")
        # Wait forever - scheduler runs in background
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("Received shutdown signal")
        await stop_scheduler()


if __name__ == "__main__":
    # Run the main async function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        sys.exit(0)
