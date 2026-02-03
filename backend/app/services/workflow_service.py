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
        custom_vars: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Trigger all enabled workflows for a specific event.

        Args:
            trigger_event: The event that occurred (e.g., "user_confirmed")
            user_id: ID of the user to send email to
            custom_vars: Additional custom variables to pass to email template

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
                merged_vars = {**(workflow.custom_vars or {}), **(custom_vars or {})}

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
                    scheduled_for=scheduled_for
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
                        "delay_minutes": workflow.delay_minutes,
                        "recipient_user_id": user_id
                    }
                )

                queued_count += 1
                logger.info(
                    f"Triggered workflow '{workflow.name}' for user {user_id} "
                    f"(trigger: {trigger_event}, template: {workflow.template_name})"
                )

            except Exception as e:
                logger.error(
                    f"Failed to trigger workflow '{workflow.name}' for user {user_id}: {str(e)}"
                )

        return queued_count

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
