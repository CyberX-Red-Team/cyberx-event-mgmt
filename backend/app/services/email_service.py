"""Email service for SendGrid integration."""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy import select, func, and_, or_, desc, cast, Date, text
from sqlalchemy.ext.asyncio import AsyncSession
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment, FileContent, FileName, FileType, Disposition, MailSettings, SandBoxMode

from app.models.user import User
from app.models.audit_log import EmailEvent
from app.models.email_template import EmailTemplate
from app.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()


def build_event_template_vars(event) -> Dict[str, str]:
    """
    Build template variables for an event.

    Args:
        event: Event model instance

    Returns:
        Dictionary with event_name, event_date_range, event_time, event_location
    """
    # Format event date range
    if event.start_date and event.end_date:
        if event.start_date == event.end_date:
            event_date_range = event.start_date.strftime("%b %d, %Y")
        else:
            # Multi-day event
            if event.start_date.month == event.end_date.month:
                event_date_range = f"{event.start_date.strftime('%b %d')} — {event.end_date.strftime('%d, %Y')}"
            else:
                event_date_range = f"{event.start_date.strftime('%b %d')} — {event.end_date.strftime('%b %d, %Y')}"
    elif event.start_date:
        event_date_range = event.start_date.strftime("%b %d, %Y")
    else:
        event_date_range = "TBA"

    return {
        "event_name": event.name,
        "event_date_range": event_date_range,
        "event_time": event.event_time or "Doors open 18:00 UTC",
        "event_location": event.event_location or "Austin, TX"
    }


async def queue_invitation_email_for_user(
    user: User,
    event,
    session: AsyncSession,
    force: bool = False
):
    """
    Queue an invitation email for a user with confirmation code.

    This helper consolidates the invitation email logic used across:
    - Admin creating participants
    - Admin resending invitations
    - Sponsor creating invitees
    - Sponsor resending invitations
    - Automated bulk invitations

    Args:
        user: User to send invitation to
        event: Event model instance
        session: Database session
        force: If True, bypass 24-hour duplicate check (for resends)

    Returns:
        EmailQueue entry that was created or found

    Raises:
        Exception: If queueing fails
    """
    import secrets
    from sqlalchemy import update
    from app.services.email_queue_service import EmailQueueService

    # Generate confirmation code
    confirmation_code = secrets.token_urlsafe(32)

    # Update user with confirmation code and timestamp
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            confirmation_code=confirmation_code,
            confirmation_sent_at=datetime.now(timezone.utc)
        )
    )

    # Create or update EventParticipation record
    # This ensures invitees have formal participation tracking for access control
    from app.models.event import EventParticipation, ParticipationStatus

    result = await session.execute(
        select(EventParticipation).where(
            EventParticipation.user_id == user.id,
            EventParticipation.event_id == event.id
        )
    )
    participation = result.scalar_one_or_none()

    if not participation:
        # Create new EventParticipation record with "invited" status
        participation = EventParticipation(
            user_id=user.id,
            event_id=event.id,
            status=ParticipationStatus.INVITED.value,
            invited_at=datetime.now(timezone.utc),
            invited_by_user_id=None  # Automated invitation (no specific admin)
        )
        session.add(participation)
        logger.info(
            f"Created EventParticipation record for user {user.id} ({user.email}) "
            f"in event {event.id} ({event.name})"
        )
    else:
        # Update existing record's invited_at timestamp (for resends)
        participation.invited_at = datetime.now(timezone.utc)
        logger.debug(
            f"Updated EventParticipation invited_at for user {user.id} ({user.email}) "
            f"in event {event.id} ({event.name})"
        )

    # Build confirmation URL
    confirmation_url = f"{settings.FRONTEND_URL}/confirm?code={confirmation_code}"

    # Log confirmation URL to console in staging environment
    # (useful when email sandbox mode is enabled)
    if settings.ENVIRONMENT == "staging":
        logger.info(
            f"\n{'='*80}\n"
            f"📧 STAGING INVITATION EMAIL\n"
            f"{'='*80}\n"
            f"To: {user.email} (ID: {user.id})\n"
            f"Name: {user.first_name} {user.last_name}\n"
            f"Event: {event.name} (ID: {event.id})\n"
            f"\n🔗 CONFIRMATION LINK:\n"
            f"{confirmation_url}\n"
            f"{'='*80}\n"
        )

    # Build event variables
    event_vars = build_event_template_vars(event)

    # Resolve template name from bulk_invite workflow config (falls back to hardcoded default)
    from app.models.email_workflow import EmailWorkflow, WorkflowTriggerEvent
    workflow_result = await session.execute(
        select(EmailWorkflow)
        .where(EmailWorkflow.trigger_event == WorkflowTriggerEvent.BULK_INVITE)
        .where(EmailWorkflow.is_enabled == True)
        .limit(1)
    )
    workflow = workflow_result.scalar_one_or_none()
    template_name = workflow.template_name if workflow else "sg_test_hacker_theme"
    workflow_vars = workflow.custom_vars if workflow and workflow.custom_vars else {}

    # Inject sender overrides if configured on the workflow
    if workflow and workflow.from_email:
        workflow_vars["__from_email"] = workflow.from_email
    if workflow and workflow.from_name:
        workflow_vars["__from_name"] = workflow.from_name

    # Queue the invitation email
    email_service = EmailQueueService(session)
    queue_entry = await email_service.enqueue_email(
        user_id=user.id,
        template_name=template_name,
        priority=3,  # High priority for invitations
        force=force,
        custom_vars={
            **workflow_vars,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "confirmation_url": confirmation_url,
            **event_vars
        }
    )

    return queue_entry


class EmailService:
    """Service for sending emails via SendGrid."""

    def __init__(self, session: AsyncSession):
        """Initialize email service."""
        self.session = session
        self.client = SendGridAPIClient(settings.SENDGRID_API_KEY)
        self.from_email = Email(settings.SENDGRID_FROM_EMAIL, settings.SENDGRID_FROM_NAME)

    # =========================================================================
    # Template Management Methods
    # =========================================================================

    async def get_templates(self, active_only: bool = True) -> List[EmailTemplate]:
        """Get all email templates."""
        query = select(EmailTemplate)
        if active_only:
            query = query.where(EmailTemplate.is_active == True)
        query = query.order_by(EmailTemplate.display_name)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_template_by_id(self, template_id: int) -> Optional[EmailTemplate]:
        """Get a template by ID."""
        result = await self.session.execute(
            select(EmailTemplate).where(EmailTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    async def get_template_by_name(self, name: str) -> Optional[EmailTemplate]:
        """Get a template by name."""
        result = await self.session.execute(
            select(EmailTemplate).where(EmailTemplate.name == name)
        )
        return result.scalar_one_or_none()

    async def create_template(
        self,
        name: str,
        display_name: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        description: Optional[str] = None,
        sendgrid_template_id: Optional[str] = None,
        available_variables: Optional[List[str]] = None,
        created_by_id: Optional[int] = None
    ) -> EmailTemplate:
        """Create a new email template."""
        template = EmailTemplate(
            name=name,
            display_name=display_name,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            description=description,
            sendgrid_template_id=sendgrid_template_id,
            available_variables=available_variables or [],
            is_system=False,
            created_by_id=created_by_id
        )
        self.session.add(template)
        await self.session.commit()
        await self.session.refresh(template)
        return template

    async def update_template(
        self,
        template_id: int,
        **kwargs
    ) -> Optional[EmailTemplate]:
        """Update an email template."""
        template = await self.get_template_by_id(template_id)
        if not template:
            return None

        # Update allowed fields
        allowed_fields = ['display_name', 'description', 'sendgrid_template_id', 'subject',
                          'html_content', 'text_content', 'available_variables', 'is_active']
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                setattr(template, field, value)

        template.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(template)
        return template

    async def delete_template(self, template_id: int) -> Tuple[bool, str]:
        """Delete a template (only non-system templates)."""
        template = await self.get_template_by_id(template_id)
        if not template:
            return False, "Template not found"
        if template.is_system:
            return False, "Cannot delete system templates"

        await self.session.delete(template)
        await self.session.commit()
        return True, "Template deleted successfully"

    async def duplicate_template(self, template_id: int, new_name: str) -> Optional[EmailTemplate]:
        """Duplicate a template with a new name."""
        original = await self.get_template_by_id(template_id)
        if not original:
            return None

        new_template = EmailTemplate(
            name=new_name,
            display_name=f"{original.display_name} (Copy)",
            description=original.description,
            subject=original.subject,
            html_content=original.html_content,
            text_content=original.text_content,
            available_variables=original.available_variables.copy() if original.available_variables else [],
            is_system=False
        )
        self.session.add(new_template)
        await self.session.commit()
        await self.session.refresh(new_template)
        return new_template

    def _render_template_content(
        self,
        template: EmailTemplate,
        user: User,
        custom_vars: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str, str]:
        """
        Render a template with user data.

        Returns:
            Tuple of (subject, html_content, text_content)
        """
        # Build template variables
        # Use confirmation_code if available (new system), otherwise fall back to invite_id (legacy)
        confirmation_param = f"code={user.confirmation_code}" if user.confirmation_code else f"{user.invite_id or user.id}"

        vars = {
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "email": user.email or "",
            "pandas_username": user.pandas_username or "",
            "pandas_password": user.pandas_password or "",
            "event_name": "2025",  # TODO: Make configurable from active event
            "confirm_url": f"{settings.FRONTEND_URL}/confirm?{confirmation_param}",  # Legacy variable name
            "confirmation_url": f"{settings.FRONTEND_URL}/confirm?{confirmation_param}",  # New variable name
            "login_url": f"{settings.FRONTEND_URL}/login",
            "survey_url": f"{settings.FRONTEND_URL}/survey",
            "orientation_date": "TBD",
            "orientation_time": "TBD",
            "orientation_location": "TBD",
            "announcement_title": "",
            "announcement_body": "",
            "start_date": "TBD",
            "start_time": "TBD",
        }

        # Merge custom variables (these will override defaults if provided)
        if custom_vars:
            vars.update(custom_vars)

        # Render template with safe formatting
        try:
            subject = template.subject.format(**vars)
            html_content = template.html_content.format(**vars)
            text_content = template.text_content.format(**vars) if template.text_content else ""
        except KeyError as e:
            # If a variable is missing, log the error and available variables
            missing_var = str(e).strip("'\"")
            logger.error(
                f"Missing template variable '{missing_var}' in template '{template.name}'. "
                f"Available custom_vars: {list(custom_vars.keys()) if custom_vars else 'None'}. "
                f"User: {user.email} (ID: {user.id})"
            )
            logger.debug(f"All available variables: {list(vars.keys())}")
            # Return template as-is (with placeholders)
            subject = template.subject
            html_content = template.html_content
            text_content = template.text_content or ""

        return subject, html_content, text_content

    def _create_sendgrid_dynamic_template_message(
        self,
        template: EmailTemplate,
        user: User,
        recipient_email: str,
        recipient_name: str,
        custom_vars: Optional[Dict[str, Any]] = None,
        from_email_override: Optional[Email] = None
    ) -> Mail:
        """
        Create a SendGrid Mail object using dynamic templates.

        This sends template variables to SendGrid's API and lets SendGrid
        handle the template rendering.

        Args:
            template: EmailTemplate with sendgrid_template_id set
            user: User to send to
            recipient_email: Recipient email address
            recipient_name: Recipient name
            custom_vars: Custom template variables to pass to SendGrid
            from_email_override: Optional sender address override

        Returns:
            Mail object configured for SendGrid dynamic template
        """
        # Build base template variables
        confirmation_param = f"code={user.confirmation_code}" if user.confirmation_code else f"{user.invite_id or user.id}"

        dynamic_template_data = {
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "email": user.email or "",
            "username": user.email or "",  # Portal login username (email-based auth)
            "pandas_username": user.pandas_username or "",
            "pandas_password": user.pandas_password or "",
            "confirm_url": f"{settings.FRONTEND_URL}/confirm?{confirmation_param}",
            "confirmation_url": f"{settings.FRONTEND_URL}/confirm?{confirmation_param}",
            "login_url": f"{settings.FRONTEND_URL}/login",
            "survey_url": f"{settings.FRONTEND_URL}/survey",
        }

        # Merge custom variables
        if custom_vars:
            dynamic_template_data.update(custom_vars)

        # Create message with dynamic template
        message = Mail(
            from_email=from_email_override or self.from_email,
            to_emails=To(recipient_email, recipient_name)
        )

        # Set the dynamic template ID and data
        message.template_id = template.sendgrid_template_id
        message.dynamic_template_data = dynamic_template_data

        logger.info(
            f"Created SendGrid dynamic template message: "
            f"template_id={template.sendgrid_template_id}, "
            f"variables={list(dynamic_template_data.keys())}"
        )

        return message

    async def preview_template(
        self,
        template_id: int,
        sample_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Tuple[str, str, str]]:
        """Preview a template with sample data."""
        template = await self.get_template_by_id(template_id)
        if not template:
            return None

        # Create a sample user object for preview
        class SampleUser:
            first_name = "John"
            last_name = "Doe"
            email = "john.doe@example.com"
            pandas_username = "jdoe"
            pandas_password = "sample_password"
            invite_id = "abc123"
            id = 1
            confirmation_code = "sample_confirmation_code_123"

        sample_user = SampleUser()

        # Override with provided sample data
        if sample_data:
            for key, value in sample_data.items():
                if hasattr(sample_user, key):
                    setattr(sample_user, key, value)

        return self._render_template_content(template, sample_user, sample_data)

    # =========================================================================
    # Email Sending Methods
    # =========================================================================

    async def send_email_with_template_id(
        self,
        user: User,
        template_id: int,
        custom_subject: Optional[str] = None,
        custom_vars: Optional[Dict[str, Any]] = None,
        attachment_content: Optional[str] = None,
        attachment_filename: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Send an email using a template ID.

        Returns:
            Tuple of (success, message, message_id)
        """
        template = await self.get_template_by_id(template_id)
        if not template:
            return False, f"Template with ID {template_id} not found", None

        return await self._send_email_with_template(
            user=user,
            template=template,
            custom_subject=custom_subject,
            custom_vars=custom_vars,
            attachment_content=attachment_content,
            attachment_filename=attachment_filename
        )

    async def send_email(
        self,
        user: User,
        template_name: str,
        custom_subject: Optional[str] = None,
        custom_vars: Optional[Dict[str, Any]] = None,
        attachment_content: Optional[str] = None,
        attachment_filename: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Send an email to a user using template name (backward compatible).

        Returns:
            Tuple of (success, message, message_id)
        """
        template = await self.get_template_by_name(template_name)
        if not template:
            return False, f"Template '{template_name}' not found", None

        return await self._send_email_with_template(
            user=user,
            template=template,
            custom_subject=custom_subject,
            custom_vars=custom_vars,
            attachment_content=attachment_content,
            attachment_filename=attachment_filename
        )

    async def _send_email_with_template(
        self,
        user: User,
        template: EmailTemplate,
        custom_subject: Optional[str] = None,
        custom_vars: Optional[Dict[str, Any]] = None,
        attachment_content: Optional[str] = None,
        attachment_filename: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Internal method to send an email using a template object.

        Supports both:
        1. SendGrid dynamic templates (if template.sendgrid_template_id is set)
        2. Local template rendering (legacy/fallback)

        Returns:
            Tuple of (success, message, message_id)
        """
        try:
            # Extract sender overrides from custom_vars (reserved keys)
            # These are injected by workflow_service / queue helpers and should
            # NOT be passed to the template engine.
            send_vars = dict(custom_vars) if custom_vars else {}
            override_from_email = send_vars.pop("__from_email", None)
            override_from_name = send_vars.pop("__from_name", None)
            custom_vars = send_vars if send_vars else None

            # Resolve sender address (workflow override → env default)
            from_email = self.from_email
            if override_from_email or override_from_name:
                from_email = Email(
                    override_from_email or settings.SENDGRID_FROM_EMAIL,
                    override_from_name or settings.SENDGRID_FROM_NAME
                )
                logger.info(
                    f"Using sender override: {override_from_email or settings.SENDGRID_FROM_EMAIL} "
                    f"<{override_from_name or settings.SENDGRID_FROM_NAME}>"
                )

            # Determine recipient email (with test override support)
            recipient_email = user.email
            recipient_name = f"{user.first_name} {user.last_name}"

            if settings.TEST_EMAIL_OVERRIDE:
                # Override recipient for testing
                original_email = recipient_email
                recipient_email = settings.TEST_EMAIL_OVERRIDE
                recipient_name = f"TEST: {recipient_name}"

            # Check if using SendGrid dynamic template or local rendering
            if template.sendgrid_template_id:
                # Use SendGrid dynamic template
                logger.info(f"Using SendGrid dynamic template: {template.sendgrid_template_id}")
                message = self._create_sendgrid_dynamic_template_message(
                    template=template,
                    user=user,
                    recipient_email=recipient_email,
                    recipient_name=recipient_name,
                    custom_vars=custom_vars,
                    from_email_override=from_email
                )
                subject = f"[Dynamic Template: {template.name}]"  # For logging only
            else:
                # Use local template rendering (legacy)
                logger.info(f"Using local template rendering for: {template.name}")
                subject, html_content, text_content = self._render_template_content(
                    template, user, custom_vars
                )

                # Use custom subject if provided
                if custom_subject:
                    subject = custom_subject

                # Add TEST prefix if override is enabled
                if settings.TEST_EMAIL_OVERRIDE:
                    subject = f"[TEST for {original_email}] {subject}"

                # Create message
                message = Mail(
                    from_email=from_email,
                    to_emails=To(recipient_email, recipient_name),
                    subject=subject,
                    html_content=Content("text/html", html_content),
                    plain_text_content=Content("text/plain", text_content)
                )

            # Enable sandbox mode if configured (emails validated but not delivered)
            if settings.SENDGRID_SANDBOX_MODE:
                message.mail_settings = MailSettings()
                message.mail_settings.sandbox_mode = SandBoxMode(enable=True)
                logger.info(f"Sandbox mode enabled for email to {recipient_email}")

            # Add attachment if provided
            if attachment_content and attachment_filename:
                import base64
                encoded_content = base64.b64encode(attachment_content.encode()).decode()
                attachment = Attachment(
                    FileContent(encoded_content),
                    FileName(attachment_filename),
                    FileType("text/plain"),
                    Disposition("attachment")
                )
                message.add_attachment(attachment)

            # Send email
            logger.info(
                f"Sending email: template={template.name}, to={recipient_email}, "
                f"subject='{subject}', sandbox={settings.SENDGRID_SANDBOX_MODE}"
            )
            response = self.client.send(message)
            logger.info(
                f"Email sent successfully: status_code={response.status_code}, "
                f"to={recipient_email}, template={template.name}"
            )

            # Get message ID from headers
            message_id = None
            if response.headers:
                message_id = response.headers.get("X-Message-Id")

            # Log the email event
            await self._log_email_event(
                email=user.email,
                user_id=user.id,
                event_type="sent",
                message_id=message_id,
                template_name=template.name,
                subject=subject
            )

            # Update user email status
            await self._update_user_email_status(user, template.name)

            return True, "Email sent successfully", message_id

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Failed to send email: template={template.name}, to={user.email}, "
                f"error={error_msg}", exc_info=True
            )

            # Log failed attempt
            await self._log_email_event(
                email=user.email,
                user_id=user.id,
                event_type="failed",
                message_id=None,
                template_name=template.name,
                reason=error_msg
            )

            return False, f"Failed to send email: {error_msg}", None

    async def send_custom_email(
        self,
        user: User,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Send a custom freeform email.

        Returns:
            Tuple of (success, message, message_id)
        """
        try:
            # Determine recipient email (with test override support)
            recipient_email = user.email
            recipient_name = f"{user.first_name} {user.last_name}"
            email_subject = subject

            if settings.TEST_EMAIL_OVERRIDE:
                # Override recipient for testing
                original_email = recipient_email
                recipient_email = settings.TEST_EMAIL_OVERRIDE
                recipient_name = f"TEST: {recipient_name}"
                email_subject = f"[TEST for {original_email}] {subject}"

            # Create message
            message = Mail(
                from_email=self.from_email,
                to_emails=To(recipient_email, recipient_name),
                subject=email_subject,
                html_content=Content("text/html", html_body),
                plain_text_content=Content("text/plain", text_body or "")
            )

            # Enable sandbox mode if configured
            if settings.SENDGRID_SANDBOX_MODE:
                message.mail_settings = MailSettings()
                message.mail_settings.sandbox_mode = SandBoxMode(enable=True)

            # Send email
            response = self.client.send(message)

            # Get message ID from headers
            message_id = None
            if response.headers:
                message_id = response.headers.get("X-Message-Id")

            # Log the email event
            await self._log_email_event(
                email=user.email,
                user_id=user.id,
                event_type="sent",
                message_id=message_id,
                template_name="custom",
                subject=subject
            )

            return True, "Email sent successfully", message_id

        except Exception as e:
            error_msg = str(e)

            # Log failed attempt
            await self._log_email_event(
                email=user.email,
                user_id=user.id,
                event_type="failed",
                message_id=None,
                template_name="custom",
                reason=error_msg
            )

            return False, f"Failed to send email: {error_msg}", None

    async def send_test_email(
        self,
        to_email: str,
        template_id: Optional[int] = None,
        custom_subject: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str], Optional[str]]:
        """
        Send a test email to verify SendGrid configuration.

        Returns:
            Tuple of (success, message, message_id, template_name)
        """
        try:
            template_name = None

            if template_id:
                # Use specified template
                template = await self.get_template_by_id(template_id)
                if not template:
                    return False, f"Template with ID {template_id} not found", None, None

                template_name = template.display_name

                # Render with sample data
                sample_vars = {
                    "first_name": "Test",
                    "last_name": "User",
                    "email": to_email,
                    "pandas_username": "testuser",
                    "pandas_password": "testpass123",
                    "event_name": "2025",
                    "confirm_url": "https://example.com/confirm/test",
                    "login_url": "https://example.com/login",
                    "survey_url": "https://example.com/survey",
                    "orientation_date": "January 15, 2025",
                    "orientation_time": "10:00 AM EST",
                    "orientation_location": "Virtual (Zoom)",
                    "announcement_title": "Test Announcement",
                    "announcement_body": "This is a test announcement body.",
                    "start_date": "January 20, 2025",
                    "start_time": "9:00 AM EST",
                }

                subject = custom_subject or template.subject
                html_content = template.html_content
                text_content = template.text_content or ""

                # Render variables
                for key, value in sample_vars.items():
                    subject = subject.replace(f"{{{key}}}", str(value))
                    html_content = html_content.replace(f"{{{key}}}", str(value))
                    text_content = text_content.replace(f"{{{key}}}", str(value))
            else:
                # Send a simple test email
                template_name = "Simple Test"
                subject = custom_subject or "CyberX Email Test"
                html_content = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>CyberX Email Test</h2>
<p>This is a test email from the CyberX Event Management System.</p>
<p>If you received this email, your SendGrid integration is working correctly.</p>
<hr>
<p style="color: #666; font-size: 12px;">
Sent at: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}<br>
From: CyberX Red Team
</p>
</body>
</html>
"""
                text_content = f"""CyberX Email Test

This is a test email from the CyberX Event Management System.

If you received this email, your SendGrid integration is working correctly.

Sent at: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
From: CyberX Red Team"""

            # Create and send message
            message = Mail(
                from_email=self.from_email,
                to_emails=To(to_email),
                subject=subject,
                html_content=Content("text/html", html_content),
                plain_text_content=Content("text/plain", text_content)
            )

            response = self.client.send(message)

            # Get message ID from headers
            message_id = None
            if response.headers:
                message_id = response.headers.get("X-Message-Id")

            return True, "Test email sent successfully", message_id, template_name

        except Exception as e:
            error_msg = str(e)
            return False, f"Failed to send test email: {error_msg}", None, None

    async def send_bulk_emails(
        self,
        users: List[User],
        template_name: str,
        custom_subject: Optional[str] = None,
        custom_vars: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, int, List[int], List[str]]:
        """
        Send emails to multiple users using template name.

        Returns:
            Tuple of (sent_count, failed_count, failed_ids, errors)
        """
        sent_count = 0
        failed_count = 0
        failed_ids = []
        errors = []

        for user in users:
            success, message, _ = await self.send_email(
                user=user,
                template_name=template_name,
                custom_subject=custom_subject,
                custom_vars=custom_vars
            )

            if success:
                sent_count += 1
            else:
                failed_count += 1
                failed_ids.append(user.id)
                errors.append(f"User {user.id} ({user.email}): {message}")

        return sent_count, failed_count, failed_ids, errors

    async def send_bulk_emails_with_template_id(
        self,
        users: List[User],
        template_id: int,
        custom_subject: Optional[str] = None,
        custom_vars: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, int, List[int], List[str]]:
        """
        Send emails to multiple users using template ID.

        Returns:
            Tuple of (sent_count, failed_count, failed_ids, errors)
        """
        template = await self.get_template_by_id(template_id)
        if not template:
            return 0, len(users), [u.id for u in users], [f"Template with ID {template_id} not found"]

        sent_count = 0
        failed_count = 0
        failed_ids = []
        errors = []

        for user in users:
            success, message, _ = await self._send_email_with_template(
                user=user,
                template=template,
                custom_subject=custom_subject,
                custom_vars=custom_vars
            )

            if success:
                sent_count += 1
            else:
                failed_count += 1
                failed_ids.append(user.id)
                errors.append(f"User {user.id} ({user.email}): {message}")

        return sent_count, failed_count, failed_ids, errors

    async def _log_email_event(
        self,
        email: str,
        event_type: str,
        message_id: Optional[str],
        template_name: Optional[str] = None,
        user_id: Optional[int] = None,
        subject: Optional[str] = None,
        reason: Optional[str] = None
    ):
        """Log an email event to the database."""
        event = EmailEvent(
            email_to=email,
            user_id=user_id,
            event_type=event_type,
            sendgrid_message_id=message_id,
            template_name=template_name,
            payload=json.dumps({
                "template": template_name,
                "subject": subject,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        )
        self.session.add(event)
        await self.session.commit()

    async def _update_user_email_status(self, user: User, template_name: str):
        """Update user's email tracking fields."""
        now = datetime.now(timezone.utc)

        if template_name == "invite":
            user.invite_sent = now
            user.last_invite_sent = now
        elif template_name == "password":
            user.password_email_sent = now
        elif template_name == "reminder":
            user.invite_reminder_sent = now
            user.last_invite_sent = now
        elif template_name == "survey":
            user.survey_email_sent = now
        elif template_name == "orientation":
            user.orientation_invite_email_sent = now

        await self.session.commit()

    # Map SendGrid event types → User.email_status values
    _EMAIL_STATUS_MAP = {
        "bounce": "BOUNCED",
        "dropped": "BOUNCED",
        "spamreport": "SPAM_REPORTED",
        "unsubscribe": "UNSUBSCRIBED",
        "group_unsubscribe": "UNSUBSCRIBED",
    }

    async def process_webhook_event(self, event_data: Dict[str, Any]) -> bool:
        """
        Process a SendGrid webhook event.

        Handles: processed, deferred, delivered, open, click, bounce,
        dropped, spamreport, unsubscribe, group_unsubscribe, group_resubscribe.

        Updates User.email_status to the appropriate granular value
        (GOOD / BOUNCED / SPAM_REPORTED / UNSUBSCRIBED) and records every
        event in the email_events table for auditing.

        Returns:
            True if processed successfully
        """
        try:
            email = event_data.get("email")
            event_type = event_data.get("event")
            sg_message_id = event_data.get("sg_message_id")
            sg_event_id = event_data.get("sg_event_id")
            reason = event_data.get("reason")
            event_timestamp = event_data.get("timestamp")

            if not email or not event_type:
                return False

            # Look up user by normalized email (handles case / Gmail alias differences)
            from app.api.utils.validation import normalize_email
            normalized = normalize_email(email)
            result = await self.session.execute(
                select(User).where(User.email_normalized == normalized)
            )
            user = result.scalar_one_or_none()

            # Record the event
            event = EmailEvent(
                user_id=user.id if user else None,
                email_to=email,
                event_type=event_type,
                sendgrid_event_id=sg_event_id,
                sendgrid_message_id=sg_message_id,
                payload=json.dumps(event_data)
            )
            self.session.add(event)

            # Update user email_status based on event type
            if user:
                new_status = self._EMAIL_STATUS_MAP.get(event_type)
                if new_status:
                    user.email_status = new_status
                    user.email_status_timestamp = event_timestamp or int(
                        datetime.now(timezone.utc).timestamp()
                    )
                    logger.warning(
                        f"Email status for user {user.id} ({email}) set to "
                        f"{new_status} due to {event_type}"
                        f"{f': {reason}' if reason else ''}"
                    )
                elif event_type == "group_resubscribe":
                    user.email_status = "GOOD"
                    user.email_status_timestamp = event_timestamp or int(
                        datetime.now(timezone.utc).timestamp()
                    )
                    logger.info(
                        f"Email status for user {user.id} ({email}) "
                        f"restored to GOOD via group_resubscribe"
                    )

            await self.session.commit()
            return True

        except Exception as e:
            logger.error(f"Error processing webhook event: {e}", exc_info=True)
            return False

    async def get_email_stats(self) -> Dict[str, int]:
        """Get email statistics."""
        stats = {
            "total_sent": 0,
            "delivered": 0,
            "opened": 0,
            "clicked": 0,
            "bounced": 0,
            "spam_reports": 0
        }

        # Count sent
        result = await self.session.execute(
            select(func.count(EmailEvent.id)).where(EmailEvent.event_type == "sent")
        )
        stats["total_sent"] = result.scalar() or 0

        # Count delivered
        result = await self.session.execute(
            select(func.count(EmailEvent.id)).where(EmailEvent.event_type == "delivered")
        )
        stats["delivered"] = result.scalar() or 0

        # Count opened
        result = await self.session.execute(
            select(func.count(EmailEvent.id)).where(EmailEvent.event_type == "open")
        )
        stats["opened"] = result.scalar() or 0

        # Count clicked
        result = await self.session.execute(
            select(func.count(EmailEvent.id)).where(EmailEvent.event_type == "click")
        )
        stats["clicked"] = result.scalar() or 0

        # Count bounced
        result = await self.session.execute(
            select(func.count(EmailEvent.id)).where(EmailEvent.event_type.in_(["bounce", "dropped"]))
        )
        stats["bounced"] = result.scalar() or 0

        # Count spam reports
        result = await self.session.execute(
            select(func.count(EmailEvent.id)).where(EmailEvent.event_type == "spamreport")
        )
        stats["spam_reports"] = result.scalar() or 0

        return stats

    async def get_user_email_events(self, user_id: int) -> List[EmailEvent]:
        """Get email events for a specific user."""
        # First get user email
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return []

        # Get events for this email
        result = await self.session.execute(
            select(EmailEvent)
            .where(EmailEvent.email_to == user.email)
            .order_by(EmailEvent.created_at.desc())
            .limit(50)
        )
        return list(result.scalars().all())

    # =========================================================================
    # Analytics Methods
    # =========================================================================

    async def get_analytics(self) -> Dict[str, Any]:
        """Get aggregated email analytics with rates."""
        stats = await self.get_email_stats()

        total_sent = stats["total_sent"]
        delivered = stats["delivered"]
        opened = stats["opened"]
        clicked = stats["clicked"]
        bounced = stats["bounced"]

        # Calculate rates (avoid division by zero)
        delivery_rate = (delivered / total_sent * 100) if total_sent > 0 else 0.0
        open_rate = (opened / delivered * 100) if delivered > 0 else 0.0
        click_rate = (clicked / opened * 100) if opened > 0 else 0.0
        bounce_rate = (bounced / total_sent * 100) if total_sent > 0 else 0.0

        return {
            "total_sent": total_sent,
            "total_delivered": delivered,
            "total_opened": opened,
            "total_clicked": clicked,
            "total_bounced": bounced,
            "total_spam_reports": stats["spam_reports"],
            "delivery_rate": round(delivery_rate, 2),
            "open_rate": round(open_rate, 2),
            "click_rate": round(click_rate, 2),
            "bounce_rate": round(bounce_rate, 2)
        }

    async def get_daily_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily email statistics for the last N days."""
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Query daily aggregates
        query = text("""
            SELECT
                DATE(created_at) as date,
                COUNT(*) FILTER (WHERE event_type = 'sent') as sent,
                COUNT(*) FILTER (WHERE event_type = 'delivered') as delivered,
                COUNT(*) FILTER (WHERE event_type = 'open') as opened,
                COUNT(*) FILTER (WHERE event_type = 'click') as clicked,
                COUNT(*) FILTER (WHERE event_type IN ('bounce', 'dropped')) as bounced
            FROM email_events
            WHERE created_at >= :start_date
            GROUP BY DATE(created_at)
            ORDER BY date
        """)

        result = await self.session.execute(query, {"start_date": start_date})
        rows = result.fetchall()

        return [
            {
                "date": row.date.isoformat() if row.date else "",
                "sent": row.sent or 0,
                "delivered": row.delivered or 0,
                "opened": row.opened or 0,
                "clicked": row.clicked or 0,
                "bounced": row.bounced or 0
            }
            for row in rows
        ]

    async def get_template_stats(self) -> List[Dict[str, Any]]:
        """Get email statistics grouped by template."""
        query = text("""
            SELECT
                template_name,
                COUNT(*) FILTER (WHERE event_type = 'sent') as sent,
                COUNT(*) FILTER (WHERE event_type = 'delivered') as delivered,
                COUNT(*) FILTER (WHERE event_type = 'open') as opened,
                COUNT(*) FILTER (WHERE event_type = 'click') as clicked,
                COUNT(*) FILTER (WHERE event_type IN ('bounce', 'dropped')) as bounced
            FROM email_events
            WHERE template_name IS NOT NULL
            GROUP BY template_name
            ORDER BY sent DESC
        """)

        result = await self.session.execute(query)
        rows = result.fetchall()

        # Get template info for display names
        templates = await self.get_templates(active_only=False)
        template_map = {t.name: t for t in templates}

        stats = []
        for row in rows:
            template = template_map.get(row.template_name)
            sent = row.sent or 0
            delivered = row.delivered or 0
            opened = row.opened or 0

            stats.append({
                "template_id": template.id if template else None,
                "template_name": row.template_name,
                "display_name": template.display_name if template else row.template_name,
                "sent": sent,
                "delivered": delivered,
                "opened": opened,
                "clicked": row.clicked or 0,
                "bounced": row.bounced or 0,
                "open_rate": round((opened / delivered * 100), 2) if delivered > 0 else 0.0,
                "click_rate": round((row.clicked / opened * 100), 2) if opened > 0 else 0.0
            })

        return stats

    async def get_email_history(
        self,
        search: Optional[str] = None,
        template_name: Optional[str] = None,
        status: Optional[str] = None,
        days: Optional[int] = 30,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get paginated email history.

        Returns:
            Tuple of (items, total_count)
        """
        # Build base query for sent emails
        query = (
            select(EmailEvent, User)
            .outerjoin(User, EmailEvent.user_id == User.id)
            .where(EmailEvent.event_type == 'sent')
        )

        # Apply filters
        if days:
            start_date = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.where(EmailEvent.created_at >= start_date)

        if template_name:
            query = query.where(EmailEvent.template_name == template_name)

        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    EmailEvent.email_to.ilike(search_term),
                    User.first_name.ilike(search_term),
                    User.last_name.ilike(search_term)
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.order_by(desc(EmailEvent.created_at)).offset(offset).limit(page_size)

        result = await self.session.execute(query)
        rows = result.fetchall()

        # Get latest status for each email
        items = []
        for row in rows:
            event = row[0]
            user = row[1]

            # Get latest event for this message ID to determine status
            latest_status = "sent"
            last_event_at = event.created_at
            if event.sendgrid_message_id:
                status_query = (
                    select(EmailEvent)
                    .where(EmailEvent.sendgrid_message_id == event.sendgrid_message_id)
                    .order_by(desc(EmailEvent.created_at))
                    .limit(1)
                )
                status_result = await self.session.execute(status_query)
                latest_event = status_result.scalar_one_or_none()
                if latest_event:
                    latest_status = latest_event.event_type
                    last_event_at = latest_event.created_at

            # Filter by status if requested
            if status and latest_status != status:
                continue

            # Get subject from payload
            subject = None
            if event.payload:
                try:
                    payload_data = event.payload if isinstance(event.payload, dict) else json.loads(event.payload)
                    subject = payload_data.get("subject")
                except (json.JSONDecodeError, TypeError):
                    pass

            items.append({
                "id": event.id,
                "recipient_email": event.email_to,
                "recipient_name": f"{user.first_name} {user.last_name}" if user else "",
                "template_name": event.template_name,
                "subject": subject,
                "status": latest_status,
                "sent_at": event.created_at,
                "last_event_at": last_event_at
            })

        return items, total

    # =========================================================================
    # SendGrid Template Sync Methods
    # =========================================================================

    async def fetch_sendgrid_templates(self) -> Tuple[bool, str, List[Dict[str, Any]]]:
        """
        Fetch all dynamic templates from SendGrid account.

        Returns:
            Tuple of (success, message, templates_list)
        """
        try:
            # Fetch dynamic templates from SendGrid
            response = self.client.client.templates.get(
                query_params={"generations": "dynamic", "page_size": 200}
            )

            if response.status_code != 200:
                return False, f"SendGrid API error: {response.status_code}", []

            data = json.loads(response.body)
            templates = data.get("result", []) or data.get("templates", [])

            template_list = []
            for template in templates:
                template_info = {
                    "sendgrid_id": template.get("id"),
                    "name": template.get("name"),
                    "generation": template.get("generation", "dynamic"),
                    "updated_at": template.get("updated_at"),
                    "versions": []
                }

                # Get version info if available
                versions = template.get("versions", [])
                for version in versions:
                    template_info["versions"].append({
                        "id": version.get("id"),
                        "name": version.get("name"),
                        "active": version.get("active", 0) == 1,
                        "subject": version.get("subject"),
                        "updated_at": version.get("updated_at")
                    })

                template_list.append(template_info)

            return True, f"Found {len(template_list)} templates", template_list

        except Exception as e:
            return False, f"Error fetching SendGrid templates: {str(e)}", []

    async def get_sendgrid_template_detail(self, sendgrid_template_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Get detailed template content from SendGrid including HTML content.

        Returns:
            Tuple of (success, message, template_detail)
        """
        try:
            response = self.client.client.templates._(sendgrid_template_id).get()

            if response.status_code != 200:
                return False, f"SendGrid API error: {response.status_code}", None

            template_data = json.loads(response.body)

            # Find the active version
            versions = template_data.get("versions", [])
            active_version = None
            for version in versions:
                if version.get("active") == 1:
                    active_version = version
                    break

            # If no active version, use the first one
            if not active_version and versions:
                active_version = versions[0]

            if not active_version:
                return False, "No template version found", None

            template_detail = {
                "sendgrid_id": template_data.get("id"),
                "name": template_data.get("name"),
                "subject": active_version.get("subject", ""),
                "html_content": active_version.get("html_content", ""),
                "plain_content": active_version.get("plain_content", ""),
                "version_id": active_version.get("id"),
                "version_name": active_version.get("name"),
                "updated_at": active_version.get("updated_at")
            }

            return True, "Template fetched successfully", template_detail

        except Exception as e:
            return False, f"Error fetching template detail: {str(e)}", None

    async def import_sendgrid_template(
        self,
        sendgrid_template_id: str,
        local_name: Optional[str] = None,
        created_by_id: Optional[int] = None
    ) -> Tuple[bool, str, Optional[EmailTemplate]]:
        """
        Import a single SendGrid template into the local database.

        Returns:
            Tuple of (success, message, template)
        """
        # Fetch template detail from SendGrid
        success, message, detail = await self.get_sendgrid_template_detail(sendgrid_template_id)
        if not success or not detail:
            return False, message, None

        # Generate a local name if not provided
        sg_name = detail.get("name", "imported_template")
        name = local_name or f"sg_{sg_name.lower().replace(' ', '_').replace('-', '_')}"

        # Check if already exists
        existing = await self.get_template_by_name(name)
        if existing:
            return False, f"Template with name '{name}' already exists", None

        # Extract variables from template content
        html_content = detail.get("html_content", "")
        available_variables = self._extract_template_variables(html_content)

        # Create the template
        template = EmailTemplate(
            name=name,
            display_name=f"[SendGrid] {detail.get('name', 'Imported Template')}",
            description=f"Imported from SendGrid template ID: {sendgrid_template_id}",
            subject=detail.get("subject", ""),
            html_content=html_content,
            text_content=detail.get("plain_content"),
            available_variables=available_variables,
            is_system=False,
            created_by_id=created_by_id
        )
        self.session.add(template)
        await self.session.commit()
        await self.session.refresh(template)

        return True, f"Template '{name}' imported successfully", template

    async def sync_sendgrid_templates(
        self,
        created_by_id: Optional[int] = None
    ) -> Tuple[int, int, int, List[str]]:
        """
        Sync all SendGrid dynamic templates to local database.
        Skips templates that already exist (based on sendgrid ID in description).

        Returns:
            Tuple of (imported_count, skipped_count, failed_count, errors)
        """
        # Fetch all SendGrid templates
        success, message, sg_templates = await self.fetch_sendgrid_templates()
        if not success:
            return 0, 0, 0, [message]

        imported = 0
        skipped = 0
        failed = 0
        errors = []

        for sg_template in sg_templates:
            sg_id = sg_template.get("sendgrid_id")
            sg_name = sg_template.get("name", "unknown")

            if not sg_id:
                failed += 1
                errors.append(f"Template '{sg_name}' has no ID")
                continue

            # Check if already imported (look for sendgrid ID in description)
            existing_query = select(EmailTemplate).where(
                EmailTemplate.description.ilike(f"%{sg_id}%")
            )
            result = await self.session.execute(existing_query)
            if result.scalar_one_or_none():
                skipped += 1
                continue

            # Import the template
            success, msg, template = await self.import_sendgrid_template(
                sendgrid_template_id=sg_id,
                created_by_id=created_by_id
            )

            if success:
                imported += 1
            else:
                failed += 1
                errors.append(f"Template '{sg_name}': {msg}")

        return imported, skipped, failed, errors

    def _extract_template_variables(self, content: str) -> List[str]:
        """Extract variable placeholders from template content."""
        import re
        # Match both {variable} and {{variable}} patterns
        pattern = r'\{\{?\s*(\w+)\s*\}?\}'
        matches = re.findall(pattern, content)
        # Return unique variables
        return list(set(matches))
