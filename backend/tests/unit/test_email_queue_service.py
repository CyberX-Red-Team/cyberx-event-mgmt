"""
Unit tests for EmailQueueService.

Tests email queue management, batching, and duplicate protection.
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.email_queue_service import EmailQueueService
from app.models.email_queue import EmailQueue, EmailQueueStatus
from app.models.user import User, UserRole


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user for email queue tests."""
    user = User(
        email="test@test.com",
        first_name="Test",
        last_name="User",
        country="USA",
        role=UserRole.INVITEE.value
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailQueueServiceEnqueue:
    """Test email queue enqueue operations."""

    async def test_enqueue_email_basic(self, db_session: AsyncSession, test_user: User):
        """Test enqueuing a basic email."""
        service = EmailQueueService(db_session)

        email = await service.enqueue_email(
            user_id=test_user.id,
            template_name="confirmation",
            priority=5
        )

        assert email.id is not None
        assert email.user_id == test_user.id
        assert email.template_name == "confirmation"
        assert email.priority == 5
        assert email.status == EmailQueueStatus.PENDING
        assert email.recipient_email == test_user.email

    async def test_enqueue_email_with_custom_vars(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test enqueuing email with custom variables."""
        service = EmailQueueService(db_session)

        custom_vars = {"vpn_ip": "10.66.66.10", "vpn_port": "51820"}
        email = await service.enqueue_email(
            user_id=test_user.id,
            template_name="vpn_assigned",
            priority=3,
            custom_vars=custom_vars
        )

        assert email.custom_vars == custom_vars

    async def test_enqueue_email_scheduled(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test enqueuing a scheduled email."""
        service = EmailQueueService(db_session)

        scheduled_time = datetime.now(timezone.utc) + timedelta(hours=2)
        email = await service.enqueue_email(
            user_id=test_user.id,
            template_name="reminder",
            scheduled_for=scheduled_time
        )

        # SQLite may return naive datetime, so compare without timezone
        scheduled_for = email.scheduled_for
        if scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

        assert scheduled_for == scheduled_time
        assert email.status == EmailQueueStatus.PENDING

    async def test_enqueue_duplicate_pending_returns_existing(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test duplicate protection for pending emails."""
        service = EmailQueueService(db_session)

        # Enqueue first email
        first = await service.enqueue_email(
            user_id=test_user.id,
            template_name="confirmation"
        )

        # Attempt to enqueue duplicate (same user, same template, still pending)
        second = await service.enqueue_email(
            user_id=test_user.id,
            template_name="confirmation"
        )

        # Should return the same email
        assert second.id == first.id

    async def test_enqueue_duplicate_sent_blocked_within_24h(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test duplicate protection blocks recently sent emails."""
        service = EmailQueueService(db_session)

        # Create a sent email from 12 hours ago
        past_time = datetime.now(timezone.utc) - timedelta(hours=12)
        sent_email = EmailQueue(
            user_id=test_user.id,
            template_name="confirmation",
            recipient_email=test_user.email,
            recipient_name=f"{test_user.first_name} {test_user.last_name}",
            status=EmailQueueStatus.SENT,
            sent_at=past_time,
            created_at=past_time
        )
        db_session.add(sent_email)
        await db_session.commit()

        # Attempt to enqueue duplicate within 24 hours
        duplicate = await service.enqueue_email(
            user_id=test_user.id,
            template_name="confirmation"
        )

        # Should return the existing sent email, not create new one
        assert duplicate.id == sent_email.id
        assert duplicate.status == EmailQueueStatus.SENT

    async def test_enqueue_duplicate_sent_allowed_after_24h(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test duplicate allowed if previous email was sent >24h ago."""
        service = EmailQueueService(db_session)

        # Create a sent email from 25 hours ago
        past_time = datetime.now(timezone.utc) - timedelta(hours=25)
        sent_email = EmailQueue(
            user_id=test_user.id,
            template_name="confirmation",
            recipient_email=test_user.email,
            recipient_name=f"{test_user.first_name} {test_user.last_name}",
            status=EmailQueueStatus.SENT,
            sent_at=past_time,
            created_at=past_time
        )
        db_session.add(sent_email)
        await db_session.commit()

        # Should be able to enqueue new email after 24 hours
        new_email = await service.enqueue_email(
            user_id=test_user.id,
            template_name="confirmation"
        )

        # Should create a new queue entry
        assert new_email.id != sent_email.id
        assert new_email.status == EmailQueueStatus.PENDING

    async def test_enqueue_with_force_bypasses_24h_check(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test force=True bypasses 24-hour duplicate check."""
        service = EmailQueueService(db_session)

        # Create a sent email from 12 hours ago
        past_time = datetime.now(timezone.utc) - timedelta(hours=12)
        sent_email = EmailQueue(
            user_id=test_user.id,
            template_name="confirmation",
            recipient_email=test_user.email,
            recipient_name=f"{test_user.first_name} {test_user.last_name}",
            status=EmailQueueStatus.SENT,
            sent_at=past_time,
            created_at=past_time
        )
        db_session.add(sent_email)
        await db_session.commit()

        # Force resend
        forced = await service.enqueue_email(
            user_id=test_user.id,
            template_name="confirmation",
            force=True
        )

        # Should create new email even within 24 hours
        assert forced.id != sent_email.id
        assert forced.status == EmailQueueStatus.PENDING

    async def test_enqueue_nonexistent_user_raises_error(self, db_session: AsyncSession):
        """Test enqueuing email for non-existent user raises error."""
        service = EmailQueueService(db_session)

        with pytest.raises(ValueError, match="User .* not found"):
            await service.enqueue_email(
                user_id=99999,
                template_name="confirmation"
            )


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailQueueServiceRetrieval:
    """Test email queue retrieval operations."""

    async def test_get_pending_emails(self, db_session: AsyncSession, test_user: User):
        """Test getting pending emails."""
        service = EmailQueueService(db_session)

        # Create pending emails
        await service.enqueue_email(test_user.id, "template1", priority=1)
        await service.enqueue_email(test_user.id, "template2", priority=2)

        # Get pending
        pending = await service.get_pending_emails()

        assert len(pending) == 2
        # Should be ordered by priority (lower number first)
        assert pending[0].priority == 1
        assert pending[1].priority == 2

    async def test_get_pending_emails_excludes_non_pending(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test get_pending_emails excludes sent/failed emails."""
        service = EmailQueueService(db_session)

        # Create emails with various statuses
        pending = EmailQueue(
            user_id=test_user.id,
            template_name="pending",
            recipient_email=test_user.email,
            recipient_name=f"{test_user.first_name} {test_user.last_name}",
            status=EmailQueueStatus.PENDING
        )
        sent = EmailQueue(
            user_id=test_user.id,
            template_name="sent",
            recipient_email=test_user.email,
            recipient_name=f"{test_user.first_name} {test_user.last_name}",
            status=EmailQueueStatus.SENT
        )
        failed = EmailQueue(
            user_id=test_user.id,
            template_name="failed",
            recipient_email=test_user.email,
            recipient_name=f"{test_user.first_name} {test_user.last_name}",
            status=EmailQueueStatus.FAILED
        )
        db_session.add_all([pending, sent, failed])
        await db_session.commit()

        # Should only get pending
        result = await service.get_pending_emails()
        assert len(result) == 1
        assert result[0].template_name == "pending"

    async def test_get_pending_emails_with_template_filter(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test filtering pending emails by template."""
        service = EmailQueueService(db_session)

        # Create second user to avoid duplicate protection
        user2 = User(
            email="test2@test.com",
            first_name="Test2",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value
        )
        db_session.add(user2)
        await db_session.commit()
        await db_session.refresh(user2)

        # Create multiple templates for different users
        await service.enqueue_email(test_user.id, "confirmation")
        await service.enqueue_email(test_user.id, "vpn_assigned")
        await service.enqueue_email(user2.id, "confirmation")

        # Filter by template
        confirmations = await service.get_pending_emails(template_name="confirmation")

        assert len(confirmations) == 2
        assert all(e.template_name == "confirmation" for e in confirmations)

    async def test_get_pending_emails_batch_size_limit(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test batch size limit on get_pending_emails."""
        service = EmailQueueService(db_session)

        # Create 5 emails
        for i in range(5):
            await service.enqueue_email(test_user.id, f"template{i}")

        # Get with batch size 3
        result = await service.get_pending_emails(batch_size=3)

        assert len(result) == 3

    async def test_get_pending_emails_excludes_scheduled_future(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test scheduled emails for the future are excluded."""
        service = EmailQueueService(db_session)

        # Create email scheduled for future
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        await service.enqueue_email(
            test_user.id,
            "future_email",
            scheduled_for=future
        )

        # Create email for now
        await service.enqueue_email(test_user.id, "now_email")

        # Should only get the non-scheduled one
        result = await service.get_pending_emails()
        assert len(result) == 1
        assert result[0].template_name == "now_email"


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailQueueServiceOperations:
    """Test email queue operations."""

    async def test_cancel_email(self, db_session: AsyncSession, test_user: User):
        """Test canceling a pending email."""
        service = EmailQueueService(db_session)

        # Create pending email
        email = await service.enqueue_email(test_user.id, "confirmation")

        # Cancel it
        success = await service.cancel_email(email.id)

        assert success is True
        # Refresh to get updated status
        await db_session.refresh(email)
        assert email.status == EmailQueueStatus.CANCELLED
        assert email.processed_at is not None

    async def test_cancel_nonexistent_email(self, db_session: AsyncSession):
        """Test canceling non-existent email returns False."""
        service = EmailQueueService(db_session)

        success = await service.cancel_email(99999)
        assert success is False

    async def test_cancel_sent_email_fails(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test cannot cancel email that's already sent."""
        service = EmailQueueService(db_session)

        # Create sent email
        email = EmailQueue(
            user_id=test_user.id,
            template_name="confirmation",
            recipient_email=test_user.email,
            recipient_name=f"{test_user.first_name} {test_user.last_name}",
            status=EmailQueueStatus.SENT,
            sent_at=datetime.now(timezone.utc)
        )
        db_session.add(email)
        await db_session.commit()

        # Attempt to cancel
        success = await service.cancel_email(email.id)

        assert success is False
        # Status should remain SENT
        await db_session.refresh(email)
        assert email.status == EmailQueueStatus.SENT

    async def test_get_queue_stats(self, db_session: AsyncSession, test_user: User):
        """Test getting email queue statistics."""
        service = EmailQueueService(db_session)

        # Create emails with various statuses
        emails = [
            EmailQueue(
                user_id=test_user.id,
                template_name=f"email{i}",
                recipient_email=test_user.email,
                recipient_name=f"{test_user.first_name} {test_user.last_name}",
                status=status
            )
            for i, status in enumerate([
                EmailQueueStatus.PENDING,
                EmailQueueStatus.PENDING,
                EmailQueueStatus.SENT,
                EmailQueueStatus.FAILED,
                EmailQueueStatus.CANCELLED
            ])
        ]
        db_session.add_all(emails)
        await db_session.commit()

        # Get stats
        stats = await service.get_queue_stats()

        assert stats[EmailQueueStatus.PENDING] == 2
        assert stats[EmailQueueStatus.SENT] == 1
        assert stats[EmailQueueStatus.FAILED] == 1
        assert stats[EmailQueueStatus.CANCELLED] == 1
        assert stats[EmailQueueStatus.PROCESSING] == 0

    async def test_get_queue_stats_empty(self, db_session: AsyncSession):
        """Test queue stats when queue is empty."""
        service = EmailQueueService(db_session)

        stats = await service.get_queue_stats()

        # All counts should be 0
        assert all(count == 0 for count in stats.values())


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailQueueServiceBatchProcessing:
    """Test email queue batch processing operations."""

    async def test_process_batch_success(
        self, db_session: AsyncSession, test_user: User, mocker
    ):
        """Test batch processing with all emails sent successfully."""
        service = EmailQueueService(db_session)

        # Create pending emails
        await service.enqueue_email(test_user.id, "confirmation", priority=1)
        await service.enqueue_email(test_user.id, "welcome", priority=2)

        # Mock EmailService.send_email to succeed
        mock_send = mocker.patch(
            'app.services.email_queue_service.EmailService.send_email',
            return_value=(True, "Success", "msg_123")
        )

        # Process batch
        batch_log = await service.process_batch(batch_size=10)

        # Verify batch log
        assert batch_log.total_processed == 2
        assert batch_log.total_sent == 2
        assert batch_log.total_failed == 0
        assert batch_log.completed_at is not None
        assert mock_send.call_count == 2

        # Verify emails are marked as sent
        pending = await service.get_pending_emails()
        assert len(pending) == 0  # All should be sent

    async def test_process_batch_partial_failure(
        self, db_session: AsyncSession, test_user: User, mocker
    ):
        """Test batch processing with some emails failing."""
        service = EmailQueueService(db_session)

        # Create pending emails
        email1 = await service.enqueue_email(test_user.id, "email1", priority=1)
        email2 = await service.enqueue_email(test_user.id, "email2", priority=2)
        email3 = await service.enqueue_email(test_user.id, "email3", priority=3)

        # Mock EmailService.send_email with mixed results
        # First succeeds, second fails (with retry), third succeeds
        mock_send = mocker.patch(
            'app.services.email_queue_service.EmailService.send_email',
            side_effect=[
                (True, "Success", "msg_1"),
                (False, "SendGrid error", None),  # Will retry
                (True, "Success", "msg_3"),
            ]
        )

        # Process batch
        batch_log = await service.process_batch(batch_size=10)

        # Verify batch log
        assert batch_log.total_processed == 3
        assert batch_log.total_sent == 2  # 2 succeeded
        assert batch_log.total_failed == 1  # 1 failed
        assert mock_send.call_count == 3

        # Verify statuses
        await db_session.refresh(email1)
        await db_session.refresh(email2)
        await db_session.refresh(email3)

        assert email1.status == EmailQueueStatus.SENT
        assert email2.status == EmailQueueStatus.PENDING  # Back to pending for retry
        assert email3.status == EmailQueueStatus.SENT

    async def test_process_batch_empty_queue(
        self, db_session: AsyncSession, mocker
    ):
        """Test processing batch when queue is empty."""
        service = EmailQueueService(db_session)

        # Mock EmailService.send_email (should not be called)
        mock_send = mocker.patch(
            'app.services.email_queue_service.EmailService.send_email'
        )

        # Process batch with empty queue
        batch_log = await service.process_batch(batch_size=10)

        # Verify batch log
        assert batch_log.total_processed == 0
        assert batch_log.total_sent == 0
        assert batch_log.total_failed == 0
        assert batch_log.completed_at is not None
        assert batch_log.duration_seconds == 0
        assert mock_send.call_count == 0  # Should not send any emails

    async def test_process_batch_user_not_found(
        self, db_session: AsyncSession, mocker
    ):
        """Test batch processing handles missing users."""
        service = EmailQueueService(db_session)

        # Create email for non-existent user (manually to bypass enqueue validation)
        email = EmailQueue(
            user_id=99999,  # Non-existent user
            template_name="test",
            recipient_email="ghost@test.com",
            recipient_name="Ghost User",
            status=EmailQueueStatus.PENDING
        )
        db_session.add(email)
        await db_session.commit()

        # Mock EmailService.send_email (should not be called for missing user)
        mock_send = mocker.patch(
            'app.services.email_queue_service.EmailService.send_email'
        )

        # Process batch
        batch_log = await service.process_batch(batch_size=10)

        # Verify batch log
        assert batch_log.total_processed == 1
        assert batch_log.total_sent == 0
        assert batch_log.total_failed == 1
        assert mock_send.call_count == 0  # Should not attempt to send

        # Verify email is marked as failed
        await db_session.refresh(email)
        assert email.status == EmailQueueStatus.FAILED
        assert email.error_message == "User not found"

    async def test_process_batch_max_attempts_reached(
        self, db_session: AsyncSession, test_user: User, mocker
    ):
        """Test batch processing marks email as failed after max attempts."""
        service = EmailQueueService(db_session)

        # Create email with max_attempts = 3 and attempts = 2
        email = EmailQueue(
            user_id=test_user.id,
            template_name="test",
            recipient_email=test_user.email,
            recipient_name=f"{test_user.first_name} {test_user.last_name}",
            status=EmailQueueStatus.PENDING,
            max_attempts=3,
            attempts=2  # This will be the 3rd attempt
        )
        db_session.add(email)
        await db_session.commit()

        # Mock EmailService.send_email to fail
        mock_send = mocker.patch(
            'app.services.email_queue_service.EmailService.send_email',
            return_value=(False, "SendGrid error", None)
        )

        # Process batch
        batch_log = await service.process_batch(batch_size=10)

        # Verify batch log
        assert batch_log.total_processed == 1
        assert batch_log.total_sent == 0
        assert batch_log.total_failed == 1

        # Verify email is marked as FAILED (not PENDING)
        await db_session.refresh(email)
        assert email.status == EmailQueueStatus.FAILED
        assert email.attempts == 3  # Should increment to 3
        assert email.error_message == "SendGrid error"

    async def test_process_batch_with_template_filter(
        self, db_session: AsyncSession, test_user: User, mocker
    ):
        """Test batch processing filters by template name."""
        service = EmailQueueService(db_session)

        # Create emails with different templates
        email1 = await service.enqueue_email(test_user.id, "confirmation", priority=1)
        email2 = await service.enqueue_email(test_user.id, "welcome", priority=2)

        # Mock EmailService.send_email
        mock_send = mocker.patch(
            'app.services.email_queue_service.EmailService.send_email',
            return_value=(True, "Success", "msg_123")
        )

        # Process only "confirmation" template
        batch_log = await service.process_batch(
            batch_size=10,
            template_name="confirmation"
        )

        # Should only process 1 email
        assert batch_log.total_processed == 1
        assert batch_log.total_sent == 1
        assert mock_send.call_count == 1

        # Verify only confirmation email was sent
        await db_session.refresh(email1)
        await db_session.refresh(email2)
        assert email1.status == EmailQueueStatus.SENT
        assert email2.status == EmailQueueStatus.PENDING  # Not processed

    async def test_process_batch_respects_batch_size(
        self, db_session: AsyncSession, test_user: User, mocker
    ):
        """Test batch processing respects batch size limit."""
        service = EmailQueueService(db_session)

        # Create 5 pending emails
        for i in range(5):
            await service.enqueue_email(test_user.id, f"email{i}", priority=i)

        # Mock EmailService.send_email
        mock_send = mocker.patch(
            'app.services.email_queue_service.EmailService.send_email',
            return_value=(True, "Success", "msg_123")
        )

        # Process with batch_size=3
        batch_log = await service.process_batch(batch_size=3)

        # Should only process 3 emails
        assert batch_log.total_processed == 3
        assert batch_log.total_sent == 3
        assert mock_send.call_count == 3

        # Verify 2 emails are still pending
        pending = await service.get_pending_emails()
        assert len(pending) == 2

    async def test_process_batch_exception_handling(
        self, db_session: AsyncSession, test_user: User, mocker
    ):
        """Test batch processing handles exceptions gracefully."""
        service = EmailQueueService(db_session)

        # Create pending email
        email = await service.enqueue_email(test_user.id, "test")

        # Mock EmailService.send_email to raise exception
        mock_send = mocker.patch(
            'app.services.email_queue_service.EmailService.send_email',
            side_effect=Exception("Unexpected error")
        )

        # Process batch
        batch_log = await service.process_batch(batch_size=10)

        # Verify batch log
        assert batch_log.total_processed == 1
        assert batch_log.total_sent == 0
        assert batch_log.total_failed == 1

        # Verify email is marked as PENDING for retry (not FAILED yet)
        await db_session.refresh(email)
        assert email.status == EmailQueueStatus.PENDING
        assert "Unexpected error" in email.error_message
        assert email.attempts == 1

    async def test_process_batch_updates_batch_metadata(
        self, db_session: AsyncSession, test_user: User, mocker
    ):
        """Test batch processing updates batch metadata correctly."""
        service = EmailQueueService(db_session)

        # Create pending email
        email = await service.enqueue_email(test_user.id, "test")

        # Mock EmailService.send_email
        mock_send = mocker.patch(
            'app.services.email_queue_service.EmailService.send_email',
            return_value=(True, "Success", "msg_123")
        )

        # Process batch with custom worker_id
        batch_log = await service.process_batch(
            batch_size=10,
            worker_id="test_worker_1"
        )

        # Verify batch metadata
        assert batch_log.batch_id is not None
        assert batch_log.batch_id.startswith("batch_")
        assert batch_log.processed_by == "test_worker_1"
        assert batch_log.batch_size == 10
        assert batch_log.started_at is not None
        assert batch_log.completed_at is not None
        assert batch_log.duration_seconds >= 0

        # Verify email has batch metadata
        await db_session.refresh(email)
        assert email.batch_id == batch_log.batch_id
        assert email.processed_by == "test_worker_1"
        assert email.last_attempt_at is not None
