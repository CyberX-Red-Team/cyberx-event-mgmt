"""Email queue service for event-based email batching."""
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_queue import EmailQueue, EmailBatchLog, EmailQueueStatus
from app.models.user import User
from app.services.email_service import EmailService


logger = logging.getLogger(__name__)


class EmailQueueService:
    """Service for managing email queue and batch processing."""

    def __init__(self, session: AsyncSession):
        """Initialize email queue service."""
        self.session = session

    async def enqueue_email(
        self,
        user_id: int,
        template_name: str,
        priority: int = 5,
        custom_vars: Optional[Dict[str, Any]] = None,
        scheduled_for: Optional[datetime] = None,
        force: bool = False
    ) -> EmailQueue:
        """
        Add an email to the queue for batched sending.

        Args:
            user_id: ID of the user to send email to
            template_name: Name of the email template
            priority: Priority (lower number = higher priority, default=5)
            custom_vars: Custom template variables
            scheduled_for: When to send the email (None = send ASAP)
            force: If True, bypass 24-hour duplicate check (but still check PENDING queue)

        Returns:
            Created EmailQueue entry
        """
        # Get user info
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError(f"User {user_id} not found")

        # Check if already queued (PENDING status)
        existing = await self.session.execute(
            select(EmailQueue).where(
                and_(
                    EmailQueue.user_id == user_id,
                    EmailQueue.template_name == template_name,
                    EmailQueue.status == EmailQueueStatus.PENDING
                )
            )
        )
        existing_email = existing.scalar_one_or_none()

        if existing_email:
            logger.info(
                f"DUPLICATE PROTECTION: Email already queued (PENDING) for user {user_id} ({user.email}) "
                f"with template '{template_name}' [queue_id: {existing_email.id}, created: {existing_email.created_at}]"
            )
            return existing_email

        # Check if recently sent or processing (within last 24 hours)
        # This prevents duplicate sends if workflow triggers multiple times
        # Can be bypassed with force=True for manual resend actions
        if not force:
            recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            recent = await self.session.execute(
                select(EmailQueue).where(
                    and_(
                        EmailQueue.user_id == user_id,
                        EmailQueue.template_name == template_name,
                        EmailQueue.status.in_([EmailQueueStatus.SENT, EmailQueueStatus.PROCESSING]),
                        EmailQueue.created_at >= recent_cutoff
                    )
                )
            )
            recent_email = recent.scalar_one_or_none()

            if recent_email:
                time_since = (datetime.now(timezone.utc) - recent_email.created_at).total_seconds() / 3600
                logger.info(
                    f"DUPLICATE PROTECTION: Email recently sent/processing for user {user_id} ({user.email}) "
                    f"with template '{template_name}' [status: {recent_email.status}, "
                    f"sent: {recent_email.sent_at}, created: {time_since:.1f}h ago]. Skipping duplicate."
                )
                return recent_email
        else:
            logger.info(
                f"FORCE RESEND: Bypassing 24-hour duplicate check for user {user_id} ({user.email}) "
                f"with template '{template_name}'"
            )

        # Create queue entry
        email_queue = EmailQueue(
            user_id=user_id,
            template_name=template_name,
            recipient_email=user.email,
            recipient_name=f"{user.first_name} {user.last_name}",
            custom_vars=custom_vars,
            priority=priority,
            status=EmailQueueStatus.PENDING,
            scheduled_for=scheduled_for
        )

        self.session.add(email_queue)
        await self.session.commit()
        await self.session.refresh(email_queue)

        scheduled_info = f", scheduled for: {scheduled_for}" if scheduled_for else ""
        logger.info(
            f"Enqueued NEW email: template '{template_name}' for user {user_id} ({user.email}) "
            f"[priority: {priority}, queue_id: {email_queue.id}{scheduled_info}]"
        )

        return email_queue

    async def get_pending_emails(
        self,
        batch_size: int = 50,
        template_name: Optional[str] = None
    ) -> List[EmailQueue]:
        """
        Get pending emails to process in batch.

        Args:
            batch_size: Maximum number of emails to process
            template_name: Filter by specific template (None = all templates)

        Returns:
            List of EmailQueue entries to process
        """
        # Build query for pending emails
        query = select(EmailQueue).where(
            and_(
                EmailQueue.status == EmailQueueStatus.PENDING,
                EmailQueue.attempts < EmailQueue.max_attempts,
                or_(
                    EmailQueue.scheduled_for.is_(None),
                    EmailQueue.scheduled_for <= datetime.now(timezone.utc)
                )
            )
        ).order_by(
            EmailQueue.priority.asc(),
            EmailQueue.created_at.asc()
        ).limit(batch_size)

        # Add template filter if specified
        if template_name:
            query = query.where(EmailQueue.template_name == template_name)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def process_batch(
        self,
        batch_size: int = 50,
        template_name: Optional[str] = None,
        worker_id: Optional[str] = None
    ) -> EmailBatchLog:
        """
        Process a batch of pending emails.

        Args:
            batch_size: Maximum number of emails to send in this batch
            template_name: Process only specific template (None = all)
            worker_id: Identifier for the worker processing this batch

        Returns:
            EmailBatchLog with processing results
        """
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"

        logger.info(f"Starting email batch {batch_id} (worker: {worker_id})")
        start_time = datetime.now(timezone.utc)

        # Create batch log
        batch_log = EmailBatchLog(
            batch_id=batch_id,
            batch_size=batch_size,
            processed_by=worker_id,
            started_at=start_time
        )
        self.session.add(batch_log)
        await self.session.commit()

        try:
            # Get pending emails
            emails = await self.get_pending_emails(batch_size, template_name)

            if not emails:
                logger.info("No pending emails to process")
                batch_log.completed_at = datetime.now(timezone.utc)
                batch_log.duration_seconds = 0
                await self.session.commit()
                return batch_log

            logger.info(f"Processing {len(emails)} emails in batch {batch_id}")

            # Mark emails as processing
            for email in emails:
                email.status = EmailQueueStatus.PROCESSING
                email.batch_id = batch_id
                email.processed_by = worker_id
                email.attempts += 1
                email.last_attempt_at = datetime.now(timezone.utc)

            await self.session.commit()

            # Send emails
            email_service = EmailService(self.session)
            sent_count = 0
            failed_count = 0

            for email_queue in emails:
                try:
                    # Get fresh user data
                    result = await self.session.execute(
                        select(User).where(User.id == email_queue.user_id)
                    )
                    user = result.scalar_one_or_none()

                    if not user:
                        email_queue.status = EmailQueueStatus.FAILED
                        email_queue.error_message = "User not found"
                        failed_count += 1
                        continue

                    # Send email
                    success, message, message_id = await email_service.send_email(
                        user=user,
                        template_name=email_queue.template_name,
                        custom_vars=email_queue.custom_vars or {}
                    )

                    if success:
                        email_queue.status = EmailQueueStatus.SENT
                        email_queue.sendgrid_message_id = message_id
                        email_queue.sent_at = datetime.now(timezone.utc)
                        email_queue.processed_at = datetime.now(timezone.utc)
                        sent_count += 1
                        logger.info(
                            f"Sent {email_queue.template_name} to {user.email}"
                        )
                    else:
                        # Check if max attempts reached
                        if email_queue.attempts >= email_queue.max_attempts:
                            email_queue.status = EmailQueueStatus.FAILED
                            logger.error(
                                f"Email to {user.email} failed after {email_queue.attempts} attempts: {message}"
                            )
                        else:
                            # Retry later
                            email_queue.status = EmailQueueStatus.PENDING
                            logger.warning(
                                f"Email to {user.email} failed (attempt {email_queue.attempts}): {message}"
                            )

                        email_queue.error_message = message
                        failed_count += 1

                except Exception as e:
                    error_msg = str(e)
                    logger.error(
                        f"Exception sending email to user {email_queue.user_id}: {error_msg}"
                    )

                    if email_queue.attempts >= email_queue.max_attempts:
                        email_queue.status = EmailQueueStatus.FAILED
                    else:
                        email_queue.status = EmailQueueStatus.PENDING

                    email_queue.error_message = error_msg
                    failed_count += 1

            await self.session.commit()

            # Update batch log
            end_time = datetime.now(timezone.utc)
            batch_log.total_processed = len(emails)
            batch_log.total_sent = sent_count
            batch_log.total_failed = failed_count
            batch_log.completed_at = end_time
            batch_log.duration_seconds = int((end_time - start_time).total_seconds())

            await self.session.commit()

            logger.info(
                f"Batch {batch_id} completed: {sent_count} sent, {failed_count} failed "
                f"in {batch_log.duration_seconds}s"
            )

            return batch_log

        except Exception as e:
            logger.error(f"Batch {batch_id} failed: {str(e)}")
            batch_log.error_message = str(e)
            batch_log.completed_at = datetime.now(timezone.utc)
            await self.session.commit()
            raise

    async def cancel_email(self, email_id: int) -> bool:
        """Cancel a pending email."""
        result = await self.session.execute(
            select(EmailQueue).where(EmailQueue.id == email_id)
        )
        email = result.scalar_one_or_none()

        if not email or email.status != EmailQueueStatus.PENDING:
            return False

        email.status = EmailQueueStatus.CANCELLED
        email.processed_at = datetime.now(timezone.utc)
        await self.session.commit()

        return True

    async def get_queue_stats(self) -> Dict[str, int]:
        """Get email queue statistics."""
        from sqlalchemy import func

        # Count by status
        result = await self.session.execute(
            select(
                EmailQueue.status,
                func.count(EmailQueue.id)
            ).group_by(EmailQueue.status)
        )

        stats = {status: 0 for status in [
            EmailQueueStatus.PENDING,
            EmailQueueStatus.PROCESSING,
            EmailQueueStatus.SENT,
            EmailQueueStatus.FAILED,
            EmailQueueStatus.CANCELLED
        ]}

        for status, count in result.all():
            stats[status] = count

        return stats
