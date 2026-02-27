"""Automated invitation reminder tasks for multi-stage follow-ups."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.event import Event, EventParticipation, ParticipationStatus
from app.services.email_queue_service import EmailQueueService
from app.services.audit_service import AuditService
from app.config import get_settings

logger = logging.getLogger(__name__)


async def process_invitation_reminders():
    """
    Process multi-stage invitation reminders.

    Runs daily to check for users who need reminders at each stage:
    - Stage 1: X days after invitation (configurable, default 7 days)
    - Stage 2: Y days after invitation (configurable, default 14 days)
    - Stage 3: Z days before event starts (configurable, default 3 days)

    Only sends to users who:
    - Have confirmed=UNKNOWN (haven't responded)
    - Have been sent an invitation (confirmation_sent_at is not null)
    - Haven't received this specific reminder stage yet
    - Event is still upcoming (for stage 1 & 2) or exactly Z days away (for stage 3)
    """
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        try:
            # Get active event
            event_result = await session.execute(
                select(Event).where(Event.is_active == True).order_by(Event.year.desc())
            )
            event = event_result.scalar_one_or_none()

            if not event:
                logger.info("No active event found - skipping reminder processing")
                return

            logger.info(
                f"Processing invitation reminders for event: {event.name} "
                f"(starts: {event.start_date}, test_mode: {event.test_mode})"
            )

            # Process each reminder stage
            await process_reminder_stage_1(session, event, settings)
            await process_reminder_stage_2(session, event, settings)
            await process_reminder_stage_3(session, event, settings)

            logger.info("Invitation reminder processing complete")

        except Exception as e:
            logger.error(f"Error processing invitation reminders: {e}", exc_info=True)


async def process_reminder_stage_1(session: AsyncSession, event: Event, settings):
    """
    Process Stage 1 reminders: X days after initial invitation.

    Logic:
    - confirmation_sent_at is X days ago (within a 3-day window)
    - reminder_1_sent_at is NULL (haven't sent this reminder yet)
    - confirmed is still UNKNOWN
    - event is at least Y days away
    """
    now = datetime.now(timezone.utc)
    days_after = settings.REMINDER_1_DAYS_AFTER_INVITE
    min_days_before_event = settings.REMINDER_1_MIN_DAYS_BEFORE_EVENT

    # Check if event is far enough away
    days_until_event = (event.start_date.replace(tzinfo=timezone.utc) - now).days
    if days_until_event < min_days_before_event:
        logger.info(
            f"Stage 1: Event is only {days_until_event} days away (minimum: {min_days_before_event}) - skipping"
        )
        return

    # Find eligible users (invitation sent X days ago, within 3-day window)
    target_date_start = now - timedelta(days=days_after + 3)
    target_date_end = now - timedelta(days=days_after)

    result = await session.execute(
        select(User)
        .join(EventParticipation, and_(
            EventParticipation.user_id == User.id,
            EventParticipation.event_id == event.id
        ))
        .where(
            and_(
                EventParticipation.status.in_([
                    ParticipationStatus.INVITED.value,
                    ParticipationStatus.NO_RESPONSE.value
                ]),
                User.confirmation_sent_at.isnot(None),
                User.confirmation_sent_at >= target_date_start,
                User.confirmation_sent_at < target_date_end,
                User.reminder_1_sent_at.is_(None),
                User.is_active == True
            )
        )
    )
    users = result.scalars().all()

    if not users:
        logger.info(f"Stage 1: No eligible users found (window: {days_after}-{days_after+3} days after invite)")
        return

    # Filter by test mode (sponsors only if test mode enabled)
    if event.test_mode:
        users = [u for u in users if u.is_sponsor_role]
        logger.info(f"Stage 1: Test mode enabled - filtered to {len(users)} sponsors")

    if not users:
        logger.info("Stage 1: No eligible users after test mode filtering")
        return

    # Queue reminders
    await queue_reminders(
        session=session,
        users=users,
        event=event,
        stage=1,
        template_name="invite_reminder_1",
        days_until_event=days_until_event
    )


async def process_reminder_stage_2(session: AsyncSession, event: Event, settings):
    """
    Process Stage 2 reminders: Y days after initial invitation.

    Logic:
    - confirmation_sent_at is Y days ago (within a 3-day window)
    - reminder_2_sent_at is NULL (haven't sent this reminder yet)
    - confirmed is still UNKNOWN
    - event is at least Z days away
    """
    now = datetime.now(timezone.utc)
    days_after = settings.REMINDER_2_DAYS_AFTER_INVITE
    min_days_before_event = settings.REMINDER_2_MIN_DAYS_BEFORE_EVENT

    # Check if event is far enough away
    days_until_event = (event.start_date.replace(tzinfo=timezone.utc) - now).days
    if days_until_event < min_days_before_event:
        logger.info(
            f"Stage 2: Event is only {days_until_event} days away (minimum: {min_days_before_event}) - skipping"
        )
        return

    # Find eligible users
    target_date_start = now - timedelta(days=days_after + 3)
    target_date_end = now - timedelta(days=days_after)

    result = await session.execute(
        select(User)
        .join(EventParticipation, and_(
            EventParticipation.user_id == User.id,
            EventParticipation.event_id == event.id
        ))
        .where(
            and_(
                EventParticipation.status.in_([
                    ParticipationStatus.INVITED.value,
                    ParticipationStatus.NO_RESPONSE.value
                ]),
                User.confirmation_sent_at.isnot(None),
                User.confirmation_sent_at >= target_date_start,
                User.confirmation_sent_at < target_date_end,
                User.reminder_2_sent_at.is_(None),
                User.is_active == True
            )
        )
    )
    users = result.scalars().all()

    if not users:
        logger.info(f"Stage 2: No eligible users found (window: {days_after}-{days_after+3} days after invite)")
        return

    # Filter by test mode
    if event.test_mode:
        users = [u for u in users if u.is_sponsor_role]
        logger.info(f"Stage 2: Test mode enabled - filtered to {len(users)} sponsors")

    if not users:
        logger.info("Stage 2: No eligible users after test mode filtering")
        return

    # Queue reminders
    await queue_reminders(
        session=session,
        users=users,
        event=event,
        stage=2,
        template_name="invite_reminder_2",
        days_until_event=days_until_event
    )


async def process_reminder_stage_3(session: AsyncSession, event: Event, settings):
    """
    Process Stage 3 reminders: Z days before event starts (final reminder).

    Logic:
    - Event starts in exactly Z days (within 24-hour window)
    - reminder_3_sent_at is NULL (haven't sent this reminder yet)
    - confirmed is still UNKNOWN
    - This is the "last chance to RSVP" reminder
    """
    now = datetime.now(timezone.utc)
    days_before = settings.REMINDER_3_DAYS_BEFORE_EVENT

    # Calculate target date range (Z days before event, with 24-hour window)
    event_start_utc = event.start_date.replace(tzinfo=timezone.utc)
    target_date = event_start_utc - timedelta(days=days_before)

    # Check if today is the target date (within 24 hours)
    time_until_target = (target_date - now).total_seconds()
    if not (0 <= time_until_target < 86400):  # 86400 seconds = 24 hours
        # Not the right day yet
        return

    logger.info(
        f"Stage 3: Today is {days_before} days before event - processing final reminders"
    )

    # Find all users who still haven't confirmed
    result = await session.execute(
        select(User)
        .join(EventParticipation, and_(
            EventParticipation.user_id == User.id,
            EventParticipation.event_id == event.id
        ))
        .where(
            and_(
                EventParticipation.status.in_([
                    ParticipationStatus.INVITED.value,
                    ParticipationStatus.NO_RESPONSE.value
                ]),
                User.confirmation_sent_at.isnot(None),
                User.reminder_3_sent_at.is_(None),
                User.is_active == True
            )
        )
    )
    users = result.scalars().all()

    if not users:
        logger.info("Stage 3: No eligible users found")
        return

    # Filter by test mode
    if event.test_mode:
        users = [u for u in users if u.is_sponsor_role]
        logger.info(f"Stage 3: Test mode enabled - filtered to {len(users)} sponsors")

    if not users:
        logger.info("Stage 3: No eligible users after test mode filtering")
        return

    # Queue final reminders
    await queue_reminders(
        session=session,
        users=users,
        event=event,
        stage=3,
        template_name="invite_reminder_final",
        days_until_event=days_before
    )


async def queue_reminders(
    session: AsyncSession,
    users: list[User],
    event: Event,
    stage: int,
    template_name: str,
    days_until_event: int
):
    """
    Queue reminder emails for a list of users.

    Resolves the template name and custom_vars from the corresponding
    event_reminder workflow (configurable via admin UI), falling back
    to the hardcoded template_name if no workflow is configured.

    Args:
        session: Database session
        users: List of users to send reminders to
        event: Active event
        stage: Reminder stage (1, 2, or 3)
        template_name: Fallback email template name
        days_until_event: Number of days until event starts
    """
    # Hard guard: never send reminders if the event has already started
    now = datetime.now(timezone.utc)
    event_start_utc = event.start_date.replace(tzinfo=timezone.utc) if event.start_date else None
    if event_start_utc and event_start_utc <= now:
        logger.info(f"Stage {stage}: Event already started - skipping reminders")
        return

    settings = get_settings()
    queue_service = EmailQueueService(session)
    audit_service = AuditService(session)

    # Resolve template from workflow config (falls back to hardcoded default)
    from sqlalchemy import select
    from app.models.email_workflow import EmailWorkflow, WorkflowTriggerEvent

    stage_trigger_map = {
        1: WorkflowTriggerEvent.EVENT_REMINDER_1,
        2: WorkflowTriggerEvent.EVENT_REMINDER_2,
        3: WorkflowTriggerEvent.EVENT_REMINDER_FINAL,
    }
    trigger_event = stage_trigger_map.get(stage)

    workflow = None
    if trigger_event:
        workflow_result = await session.execute(
            select(EmailWorkflow)
            .where(EmailWorkflow.trigger_event == trigger_event)
            .where(EmailWorkflow.is_enabled == True)
            .limit(1)
        )
        workflow = workflow_result.scalar_one_or_none()

    resolved_template = workflow.template_name if workflow else template_name
    workflow_vars = workflow.custom_vars if workflow and workflow.custom_vars else {}

    # Inject sender overrides if configured on the workflow
    if workflow and workflow.from_email:
        workflow_vars["__from_email"] = workflow.from_email
    if workflow and workflow.from_name:
        workflow_vars["__from_name"] = workflow.from_name

    logger.info(
        f"Stage {stage}: Using template '{resolved_template}' "
        f"(workflow: {'yes' if workflow else 'fallback'})"
    )

    queued_count = 0
    failed_count = 0

    for user in users:
        try:
            # Generate new confirmation code (in case original expired)
            from secrets import token_urlsafe
            confirmation_code = token_urlsafe(32)
            user.confirmation_code = confirmation_code

            # Build confirmation URL
            confirmation_url = f"{settings.FRONTEND_URL}/confirm?code={confirmation_code}"

            # Build event variables
            from app.services.email_service import build_event_template_vars
            event_vars = build_event_template_vars(event)

            # Queue email (workflow_vars first so trigger-time vars override)
            await queue_service.enqueue_email(
                user_id=user.id,
                template_name=resolved_template,
                priority=4,  # High priority for reminders
                custom_vars={
                    **workflow_vars,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "event_start_date": event.start_date.strftime("%B %d, %Y") if event.start_date else "TBA",
                    "days_until_event": days_until_event,
                    "confirmation_url": confirmation_url,
                    "is_final_reminder": (stage == 3),
                    "reminder_stage": stage,
                    **event_vars
                }
            )

            # Mark reminder as sent
            now = datetime.now(timezone.utc)
            if stage == 1:
                user.reminder_1_sent_at = now
            elif stage == 2:
                user.reminder_2_sent_at = now
            elif stage == 3:
                user.reminder_3_sent_at = now

            # Audit log
            await audit_service.log_reminder_sent(
                user_id=user.id,
                target_user_id=user.id,
                stage=stage,
                event_id=event.id,
                event_name=event.name,
                template_name=template_name,
                days_until_event=days_until_event
            )

            queued_count += 1

        except Exception as e:
            failed_count += 1
            logger.error(
                f"Failed to queue Stage {stage} reminder for user {user.id} ({user.email}): {e}"
            )

    await session.commit()

    logger.info(
        f"Stage {stage}: Queued {queued_count} reminders, {failed_count} failed "
        f"(template: {resolved_template}, days until event: {days_until_event})"
    )


def schedule_invitation_reminder_job(scheduler):
    """
    Schedule the invitation reminder job to run daily.

    Args:
        scheduler: APScheduler instance
    """
    settings = get_settings()
    interval_hours = settings.REMINDER_CHECK_INTERVAL_HOURS

    scheduler.add_job(
        func=process_invitation_reminders,
        trigger='interval',
        hours=interval_hours,
        id='invitation_reminders',
        name='Invitation Reminders Processor',
        replace_existing=True
    )

    logger.info(
        f"Scheduled invitation reminders job to run every {interval_hours} hours"
    )
