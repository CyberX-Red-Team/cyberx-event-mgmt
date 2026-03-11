"""Automated invitation email task for event activation."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, and_, or_

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.event import EventParticipation, ParticipationStatus


logger = logging.getLogger(__name__)


async def send_invitations_to_unknown_participants(event_id: int, event_name: str, test_mode: bool = False):
    """
    Queue invitation emails for participants with UNKNOWN confirmation status.

    This function is called 30 seconds after an event becomes active or enters test mode.
    - In test mode: Sends to sponsors only (regardless of registration status)
    - In production mode: Only sends if registration is open

    Args:
        event_id: The ID of the event that was activated
        event_name: The name of the event for logging purposes
        test_mode: If True, only send to sponsors. If False, send to all invitees and sponsors (only if registration open)
    """
    logger.info(
        f"Starting automated invitation emails for event: {event_name} (ID: {event_id}) "
        f"[test_mode={test_mode}]"
    )

    # Get database session
    async with AsyncSessionLocal() as session:
        try:
            # Load event to check registration status
            from app.models.event import Event
            event_result = await session.execute(
                select(Event).where(Event.id == event_id)
            )
            event = event_result.scalar_one_or_none()

            if not event:
                logger.error(f"Event {event_id} not found, cannot send invitations")
                return

            # Check registration status
            if not test_mode and not event.registration_open:
                logger.info(
                    f"Registration is closed for event {event_name} - "
                    f"skipping invitation emails (use test mode to invite sponsors)"
                )
                return

            # Find participants based on mode
            # IMPORTANT: Only send to users who have NEVER received an invitation
            # This prevents duplicate invitations if workflow is triggered multiple times
            if test_mode:
                # Test mode: Only sponsors (regardless of registration status)
                query = (
                    select(User)
                    .outerjoin(EventParticipation, and_(
                        EventParticipation.user_id == User.id,
                        EventParticipation.event_id == event.id
                    ))
                    .where(User.role == 'sponsor')
                    .where(or_(
                        # No participation record yet (newly added user)
                        EventParticipation.id.is_(None),
                        # Has participation but not confirmed/declined
                        EventParticipation.status.in_([
                            ParticipationStatus.INVITED.value,
                            ParticipationStatus.NO_RESPONSE.value
                        ])
                    ))
                    .where(User.confirmation_sent_at.is_(None))  # Never sent before
                    .where(User.is_active == True)
                )
                role_desc = "sponsors only (test mode)"
            else:
                # Production mode: All invitees and sponsors (registration must be open)
                query = (
                    select(User)
                    .outerjoin(EventParticipation, and_(
                        EventParticipation.user_id == User.id,
                        EventParticipation.event_id == event.id
                    ))
                    .where(User.role.in_(['invitee', 'sponsor']))
                    .where(or_(
                        # No participation record yet (newly added user)
                        EventParticipation.id.is_(None),
                        # Has participation but not confirmed/declined
                        EventParticipation.status.in_([
                            ParticipationStatus.INVITED.value,
                            ParticipationStatus.NO_RESPONSE.value
                        ])
                    ))
                    .where(User.confirmation_sent_at.is_(None))  # Never sent before
                    .where(User.is_active == True)
                )
                role_desc = "invitees and sponsors (registration open)"

            result = await session.execute(query)
            participants = result.scalars().all()

            if not participants:
                logger.info(f"No unconfirmed participants found for event {event_name} ({role_desc})")
                return

            # Log statistics about filtering
            # Count total not-yet-confirmed users (without confirmation_sent_at filter) for comparison
            if test_mode:
                total_query = (
                    select(User)
                    .outerjoin(EventParticipation, and_(
                        EventParticipation.user_id == User.id,
                        EventParticipation.event_id == event.id
                    ))
                    .where(User.role == 'sponsor')
                    .where(or_(
                        EventParticipation.id.is_(None),
                        EventParticipation.status.in_([
                            ParticipationStatus.INVITED.value,
                            ParticipationStatus.NO_RESPONSE.value
                        ])
                    ))
                    .where(User.is_active == True)
                )
            else:
                total_query = (
                    select(User)
                    .outerjoin(EventParticipation, and_(
                        EventParticipation.user_id == User.id,
                        EventParticipation.event_id == event.id
                    ))
                    .where(User.role.in_(['invitee', 'sponsor']))
                    .where(or_(
                        EventParticipation.id.is_(None),
                        EventParticipation.status.in_([
                            ParticipationStatus.INVITED.value,
                            ParticipationStatus.NO_RESPONSE.value
                        ])
                    ))
                    .where(User.is_active == True)
                )

            total_result = await session.execute(total_query)
            total_unknown = len(list(total_result.scalars().all()))

            filtered_out = total_unknown - len(participants)

            logger.info(
                f"Found {len(participants)} participants to invite for event {event_name} ({role_desc}). "
                f"Total UNKNOWN users: {total_unknown}. "
                f"Filtered out {filtered_out} users (already received invitation - duplicate protection)."
            )

            # Queue invitation email for each participant
            queued_count = 0
            duplicate_count = 0
            failed_count = 0

            for participant in participants:
                try:
                    # Queue invitation email using helper function
                    from app.services.email_service import queue_invitation_email_for_user
                    queue_entry = await queue_invitation_email_for_user(
                        user=participant,
                        event=event,
                        session=session,
                        force=False
                    )

                    # Check if this was newly created (within last 5 seconds) or a duplicate
                    if (datetime.now(timezone.utc) - queue_entry.created_at).total_seconds() < 5:
                        queued_count += 1
                    else:
                        duplicate_count += 1

                except Exception as e:
                    failed_count += 1
                    logger.error(
                        f"Failed to queue invitation for participant {participant.id} ({participant.email}): {e}"
                    )

            await session.commit()

            # Log summary with breakdown
            logger.info(
                f"Invitation queueing complete for event {event_name}: "
                f"{queued_count} new emails queued, "
                f"{duplicate_count} duplicates skipped, "
                f"{failed_count} failed"
            )

        except Exception as e:
            logger.error(f"Error in send_invitations_to_unknown_participants: {e}", exc_info=True)
            await session.rollback()


def schedule_invitation_emails(event_id: int, event_name: str, test_mode: bool = False):
    """
    Schedule the invitation email task to run after 30 seconds.

    Uses a consistent job_id (without timestamp) so that multiple rapid triggers
    will replace the pending job rather than creating duplicates.

    IMPORTANT: When scheduling, this cancels BOTH test and prod jobs to prevent
    orphaned jobs from test mode toggles.

    Args:
        event_id: The ID of the event that was activated
        event_name: The name of the event
        test_mode: If True, only send to sponsors. If False, send to all invitees and sponsors
    """
    from app.tasks.scheduler import get_scheduler

    scheduler = get_scheduler()

    # Schedule the task to run once after 30 seconds (use UTC timezone)
    run_date = datetime.now(timezone.utc) + timedelta(seconds=30)

    # Use consistent job_id (no timestamp) so replace_existing=True actually works
    # This prevents duplicate jobs if workflow is triggered multiple times quickly
    mode_suffix = "test" if test_mode else "prod"
    job_id = f"invitation_emails_event_{event_id}_{mode_suffix}"

    # CRITICAL: Cancel BOTH test and prod job variants to prevent orphaned jobs
    # When test mode is toggled, the job_id changes (test vs prod suffix)
    # Without this, both jobs would exist and run independently!
    test_job_id = f"invitation_emails_event_{event_id}_test"
    prod_job_id = f"invitation_emails_event_{event_id}_prod"

    cancelled_jobs = []
    for cancel_job_id in [test_job_id, prod_job_id]:
        existing = scheduler.get_job(cancel_job_id)
        if existing:
            scheduler.remove_job(cancel_job_id)
            cancelled_jobs.append(f"{cancel_job_id} (was: {existing.next_run_time})")
            logger.info(f"Cancelled existing invitation job: {cancel_job_id}")

    if cancelled_jobs:
        logger.info(
            f"TEST MODE TOGGLE PROTECTION: Cancelled {len(cancelled_jobs)} existing job(s) "
            f"before scheduling new job for event '{event_name}': {', '.join(cancelled_jobs)}"
        )

    # Schedule the new job
    scheduler.add_job(
        func=send_invitations_to_unknown_participants,
        trigger='date',
        run_date=run_date,
        args=[event_id, event_name, test_mode],
        id=job_id,
        name=f"Queue invitations for {event_name}",
        replace_existing=True
    )

    mode_desc = "sponsors only (test mode)" if test_mode else "all invitees and sponsors"
    logger.info(
        f"Scheduled invitation email job for event '{event_name}' to run at {run_date} "
        f"(in 30 seconds) - {mode_desc} [job_id: {job_id}]"
    )
