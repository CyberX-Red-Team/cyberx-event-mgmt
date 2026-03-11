"""Workflow service for triggering email workflows based on events."""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_workflow import EmailWorkflow, WorkflowTriggerEvent
from app.models.user import User
from app.models.event import Event
from app.services.email_queue_service import EmailQueueService
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class WorkflowService:
    """Service for managing and triggering email workflows."""

    def __init__(self, session: AsyncSession):
        """Initialize workflow service."""
        self.session = session

    async def trigger_workflow(
        self,
        trigger_event: str,
        user_id: int,
        custom_vars: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> int:
        """
        Trigger all enabled workflows for a specific event.

        Args:
            trigger_event: The event that occurred (e.g., "user_confirmed")
            user_id: ID of the user to send email to
            custom_vars: Additional custom variables to pass to email template
            force: If True, bypass 24-hour duplicate check in email queue

        Returns:
            Number of emails queued
        """
        # Get all enabled workflows for this trigger event
        result = await self.session.execute(
            select(EmailWorkflow).where(
                and_(
                    EmailWorkflow.trigger_event == trigger_event,
                    EmailWorkflow.is_enabled == True
                )
            ).order_by(EmailWorkflow.priority.asc())
        )
        workflows = result.scalars().all()

        if not workflows:
            logger.debug(f"No enabled workflows found for trigger event: {trigger_event}")
            return 0

        # Check if event is in test mode and restrict to sponsors only
        event_result = await self.session.execute(
            select(Event).where(Event.is_active == True).order_by(Event.year.desc())
        )
        active_event = event_result.scalar_one_or_none()

        # Get user to check if they're a sponsor
        user_result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        # TEST MODE RESTRICTION: Skip workflow if test mode is enabled and user is not a sponsor
        if active_event and active_event.test_mode:
            if not user or not user.is_sponsor_role:
                logger.info(
                    f"Skipping workflow trigger for user {user_id} (trigger: {trigger_event}) - "
                    f"test mode is enabled and user is not a sponsor"
                )
                return 0

        # Queue emails for each workflow
        queue_service = EmailQueueService(self.session)
        audit_service = AuditService(self.session)
        queued_count = 0

        for workflow in workflows:
            try:
                # Merge workflow custom vars with provided vars
                # Caller vars override workflow DB vars
                merged_vars = {**(workflow.custom_vars or {}), **(custom_vars or {})}

                logger.info(
                    "Workflow '%s': merging vars — "
                    "workflow_db_keys=%s, caller_keys=%s, merged_keys=%s, "
                    "password_present=%s",
                    workflow.name,
                    list((workflow.custom_vars or {}).keys()),
                    list((custom_vars or {}).keys()),
                    list(merged_vars.keys()),
                    "password" in merged_vars,
                )

                # Inject sender overrides if configured on the workflow
                if workflow.from_email:
                    merged_vars["__from_email"] = workflow.from_email
                if workflow.from_name:
                    merged_vars["__from_name"] = workflow.from_name

                send_mode = "immediate" if workflow.send_immediately else "queued"

                if workflow.send_immediately:
                    # Send immediately — bypass queue for time-sensitive emails
                    from app.services.email_service import EmailService
                    email_service = EmailService(self.session)
                    success, message, message_id = await email_service.send_email(
                        user=user,
                        template_name=workflow.template_name,
                        custom_vars=merged_vars,
                    )
                    if not success:
                        logger.error(
                            f"Immediate send failed for workflow '{workflow.name}', "
                            f"user {user_id}: {message}"
                        )
                        continue
                else:
                    # Calculate scheduled time if delay is specified
                    scheduled_for = None
                    if workflow.delay_minutes and workflow.delay_minutes > 0:
                        scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=workflow.delay_minutes)

                    # Enqueue email
                    await queue_service.enqueue_email(
                        user_id=user_id,
                        template_name=workflow.template_name,
                        priority=workflow.priority,
                        custom_vars=merged_vars,
                        scheduled_for=scheduled_for,
                        force=force
                    )

                # Audit log the workflow trigger
                await audit_service.log_workflow_trigger(
                    user_id=user_id,
                    workflow_id=workflow.id,
                    trigger_event=trigger_event,
                    details={
                        "workflow_name": workflow.name,
                        "template_name": workflow.template_name,
                        "priority": workflow.priority,
                        "send_mode": send_mode,
                        "delay_minutes": workflow.delay_minutes,
                        "recipient_user_id": user_id
                    }
                )

                queued_count += 1
                logger.info(
                    f"Triggered workflow '{workflow.name}' for user {user_id} "
                    f"(trigger: {trigger_event}, template: {workflow.template_name}, "
                    f"mode: {send_mode})"
                )

            except Exception as e:
                logger.error(
                    f"Failed to trigger workflow '{workflow.name}' for user {user_id}: {str(e)}"
                )

        return queued_count

    async def send_immediate(
        self,
        trigger_event: str,
        user_id: int,
        custom_vars: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Resolve workflow config and send email immediately (bypass queue).

        Uses the workflow record to determine template name, custom_vars,
        and sender overrides, but sends via EmailService.send_email() instead
        of queuing. Useful for time-sensitive emails like password resets.

        Returns:
            True if email was sent, False otherwise.
        """
        from app.services.email_service import EmailService

        # Get first enabled workflow for this trigger
        result = await self.session.execute(
            select(EmailWorkflow).where(
                and_(
                    EmailWorkflow.trigger_event == trigger_event,
                    EmailWorkflow.is_enabled == True
                )
            ).order_by(EmailWorkflow.priority.asc()).limit(1)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            logger.warning(f"No enabled workflow for '{trigger_event}', cannot send immediate email")
            return False

        # Get user
        user_result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            logger.error(f"User {user_id} not found for immediate send")
            return False

        # Merge vars: workflow DB defaults < caller overrides
        merged_vars = {**(workflow.custom_vars or {}), **(custom_vars or {})}

        # Inject sender overrides
        if workflow.from_email:
            merged_vars["__from_email"] = workflow.from_email
        if workflow.from_name:
            merged_vars["__from_name"] = workflow.from_name

        logger.info(
            "Immediate send via workflow '%s': template=%s, user=%s",
            workflow.name, workflow.template_name, user_id,
        )

        email_service = EmailService(self.session)
        success, message, message_id = await email_service.send_email(
            user=user,
            template_name=workflow.template_name,
            custom_vars=merged_vars,
        )

        if success:
            # Audit log
            audit_service = AuditService(self.session)
            await audit_service.log_workflow_trigger(
                user_id=user_id,
                workflow_id=workflow.id,
                trigger_event=trigger_event,
                details={
                    "workflow_name": workflow.name,
                    "template_name": workflow.template_name,
                    "send_mode": "immediate",
                    "recipient_user_id": user_id,
                }
            )
        else:
            logger.error(f"Immediate send failed for user {user_id}: {message}")

        return success

    async def get_workflow_by_name(self, name: str) -> Optional[EmailWorkflow]:
        """Get a workflow by its name."""
        result = await self.session.execute(
            select(EmailWorkflow).where(EmailWorkflow.name == name)
        )
        return result.scalar_one_or_none()

    async def get_workflows_by_trigger(self, trigger_event: str, enabled_only: bool = True) -> list[EmailWorkflow]:
        """Get all workflows for a specific trigger event."""
        query = select(EmailWorkflow).where(EmailWorkflow.trigger_event == trigger_event)

        if enabled_only:
            query = query.where(EmailWorkflow.is_enabled == True)

        query = query.order_by(EmailWorkflow.priority.asc())

        result = await self.session.execute(query)
        return list(result.scalars().all())
