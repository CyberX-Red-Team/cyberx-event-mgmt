"""Email API routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db, get_current_admin_user
from app.api.exceptions import not_found, forbidden, bad_request, conflict, unauthorized, server_error
from app.api.utils.pagination import calculate_pagination
from app.api.utils.validation import validate_bulk_email_permissions
from app.api.utils.dependencies import (
    get_email_service,
    get_participant_service,
    get_vpn_service
)
from app.models.user import User
from app.services.email_service import EmailService
from app.services.participant_service import ParticipantService
from app.services.vpn_service import VPNService
from app.services.audit_service import AuditService
from app.schemas.email import (
    # Template schemas
    EmailTemplateCreate,
    EmailTemplateUpdate,
    EmailTemplateResponse,
    EmailTemplateListItem,
    EmailPreviewRequest,
    EmailPreviewResponse,
    # Send schemas
    SendEmailRequest,
    SendEmailResponse,
    BulkEmailRequest,
    BulkEmailResponse,
    SendCustomEmailRequest,
    SendTestEmailRequest,
    SendTestEmailResponse,
    # Analytics schemas
    EmailAnalyticsResponse,
    DailyStatsResponse,
    DailyEmailStats,
    TemplateStatsResponse,
    TemplateStats,
    # History schemas
    EmailHistoryResponse,
    EmailHistoryItem,
    # SendGrid sync schemas
    SendGridTemplatesResponse,
    SendGridTemplateItem,
    ImportSendGridTemplateRequest,
    ImportSendGridTemplateResponse,
    SyncSendGridTemplatesResponse,
    # Legacy schemas
    EmailStatsResponse,
    ParticipantEmailStatus,
    EmailEventResponse,
)


router = APIRouter(prefix="/api/email", tags=["Email"])


def get_audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    """Get audit service dependency."""
    return AuditService(db)


@router.post("/send", response_model=SendEmailResponse)
async def send_email(
    data: SendEmailRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service),
    participant_service: ParticipantService = Depends(get_participant_service),
    audit_service: AuditService = Depends(get_audit_service)
):
    """Send an email to a single participant using a template ID."""
    # Get participant
    participant = await participant_service.get_participant(data.participant_id)
    if not participant:
        raise not_found("Participant not found")

    # Validate template exists
    template = await email_service.get_template_by_id(data.template_id)
    if not template:
        raise not_found("Template not found")

    if not template.is_active:
        raise bad_request("Template is not active")

    # Send email
    success, message, message_id = await email_service.send_email_with_template_id(
        user=participant,
        template_id=data.template_id,
        custom_subject=data.custom_subject,
        custom_vars=data.custom_variables
    )

    # Log email send to audit log
    if success:
        await audit_service.log_email_send(
            user_id=current_user.id,
            recipient_ids=[participant.id],
            template_name=template.name,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None
        )

    return SendEmailResponse(
        success=success,
        message=message,
        message_id=message_id,
        recipient_email=participant.email
    )


@router.post("/send-vpn-config", response_model=SendEmailResponse)
async def send_vpn_config_email(
    participant_id: int,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service),
    participant_service: ParticipantService = Depends(get_participant_service),
    vpn_service: VPNService = Depends(get_vpn_service),
    audit_service: AuditService = Depends(get_audit_service)
):
    """Send VPN configuration email with attachment."""
    # Get participant
    participant = await participant_service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant not found")

    # Get VPN credential
    vpn = await vpn_service.get_user_credential(participant_id)
    if not vpn:
        raise bad_request("Participant does not have a VPN assigned")

    # Generate config
    config = vpn_service.generate_wireguard_config(vpn)
    filename = vpn_service.get_config_filename(participant, vpn)

    # Send email with attachment
    success, message, message_id = await email_service.send_email(
        user=participant,
        template_name="vpn_config",
        attachment_content=config,
        attachment_filename=filename
    )

    # Log email send to audit log
    if success:
        await audit_service.log_email_send(
            user_id=current_user.id,
            recipient_ids=[participant.id],
            template_name="vpn_config",
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None
        )

    return SendEmailResponse(
        success=success,
        message=message,
        message_id=message_id,
        recipient_email=participant.email
    )


@router.post("/bulk", response_model=BulkEmailResponse)
async def send_bulk_emails(
    data: BulkEmailRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service),
    participant_service: ParticipantService = Depends(get_participant_service),
    audit_service: AuditService = Depends(get_audit_service),
    db: AsyncSession = Depends(get_db)
):
    """Send emails to multiple participants using a template ID."""
    # Validate template exists
    template = await email_service.get_template_by_id(data.template_id)
    if not template:
        raise not_found("Template not found")

    if not template.is_active:
        raise bad_request("Template is not active")

    # Get participants
    users = []
    for pid in data.participant_ids:
        participant = await participant_service.get_participant(pid)
        if participant:
            users.append(participant)

    if not users:
        raise bad_request("No valid participants found")

    # SAFEGUARD: Prevent accidental mass emails
    # Test mode ALWAYS restricts to sponsors only, regardless of registration_open
    # Validate bulk email permissions (test mode, registration open, etc.)
    await validate_bulk_email_permissions(users, db, "bulk emails")

    # Send emails
    sent, failed, failed_ids, errors = await email_service.send_bulk_emails_with_template_id(
        users=users,
        template_id=data.template_id,
        custom_subject=data.custom_subject,
        custom_vars=data.custom_variables
    )

    # Log email send to audit log
    if sent > 0:
        await audit_service.log_email_send(
            user_id=current_user.id,
            recipient_ids=[u.id for u in users if u.id not in failed_ids],
            template_name=template.name,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None
        )

    return BulkEmailResponse(
        success=sent > 0,
        message=f"Sent {sent} emails, {failed} failed",
        sent_count=sent,
        failed_count=failed,
        failed_ids=failed_ids,
        errors=errors
    )


@router.post("/send-custom", response_model=BulkEmailResponse)
async def send_custom_emails(
    data: SendCustomEmailRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service),
    participant_service: ParticipantService = Depends(get_participant_service),
    audit_service: AuditService = Depends(get_audit_service),
    db: AsyncSession = Depends(get_db)
):
    """Send custom freeform emails to multiple participants."""
    # Get participants
    users = []
    for pid in data.participant_ids:
        participant = await participant_service.get_participant(pid)
        if participant:
            users.append(participant)

    if not users:
        raise bad_request("No valid participants found")

    # Validate bulk email permissions (test mode, registration open, etc.)
    await validate_bulk_email_permissions(users, db, "custom emails")

    # Send emails
    sent_count = 0
    failed_count = 0
    failed_ids = []
    errors = []

    for user in users:
        success, message, _ = await email_service.send_custom_email(
            user=user,
            subject=data.subject,
            html_body=data.html_body,
            text_body=data.text_body
        )

        if success:
            sent_count += 1
        else:
            failed_count += 1
            failed_ids.append(user.id)
            errors.append(f"User {user.id} ({user.email}): {message}")

    # Log email send to audit log
    if sent_count > 0:
        await audit_service.log_email_send(
            user_id=current_user.id,
            recipient_ids=[u.id for u in users if u.id not in failed_ids],
            template_name="custom",
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None
        )

    return BulkEmailResponse(
        success=sent_count > 0,
        message=f"Sent {sent_count} emails, {failed_count} failed",
        sent_count=sent_count,
        failed_count=failed_count,
        failed_ids=failed_ids,
        errors=errors
    )


@router.post("/test", response_model=SendTestEmailResponse)
async def send_test_email(
    data: SendTestEmailRequest,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """
    Send a test email to verify SendGrid configuration.

    Can optionally use a template to test template rendering.
    """
    success, message, message_id, template_name = await email_service.send_test_email(
        to_email=data.to_email,
        template_id=data.template_id,
        custom_subject=data.subject
    )

    return SendTestEmailResponse(
        success=success,
        message=message,
        message_id=message_id,
        to_email=data.to_email,
        template_used=template_name
    )


@router.get("/stats", response_model=EmailStatsResponse)
async def get_email_stats(
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Get email statistics."""
    stats = await email_service.get_email_stats()
    return EmailStatsResponse(**stats)


@router.get("/participant/{participant_id}/status", response_model=ParticipantEmailStatus)
async def get_participant_email_status(
    participant_id: int,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service),
    participant_service: ParticipantService = Depends(get_participant_service)
):
    """Get email status for a participant."""
    # Get participant
    participant = await participant_service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant not found")

    # Get email events
    events = await email_service.get_user_email_events(participant_id)

    return ParticipantEmailStatus(
        participant_id=participant.id,
        email=participant.email,
        invite_sent=participant.invite_sent,
        password_email_sent=participant.password_email_sent,
        last_email_status=participant.email_status,
        events=[
            EmailEventResponse(
                id=e.id,
                email=e.email,
                event_type=e.event_type,
                timestamp=e.timestamp,
                message_id=e.sg_message_id,
                reason=e.reason
            )
            for e in events
        ]
    )


# =============================================================================
# Template Management Endpoints
# =============================================================================

@router.get("/templates", response_model=List[EmailTemplateListItem])
async def list_email_templates(
    active_only: bool = Query(True, description="Only return active templates"),
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """List all email templates."""
    templates = await email_service.get_templates(active_only=active_only)
    return [EmailTemplateListItem.model_validate(t) for t in templates]


@router.post("/templates", response_model=EmailTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_email_template(
    data: EmailTemplateCreate,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Create a new email template."""
    # Check if name already exists
    existing = await email_service.get_template_by_name(data.name)
    if existing:
        raise bad_request(f"Template with name '{data.name}' already exists")

    template = await email_service.create_template(
        name=data.name,
        display_name=data.display_name,
        subject=data.subject,
        html_content=data.html_content,
        text_content=data.text_content,
        description=data.description,
        sendgrid_template_id=data.sendgrid_template_id,
        available_variables=data.available_variables,
        created_by_id=current_user.id
    )

    return EmailTemplateResponse.model_validate(template)


@router.get("/templates/{template_id}", response_model=EmailTemplateResponse)
async def get_email_template(
    template_id: int,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Get a single email template by ID."""
    template = await email_service.get_template_by_id(template_id)
    if not template:
        raise not_found("Template not found")
    return EmailTemplateResponse.model_validate(template)


@router.put("/templates/{template_id}", response_model=EmailTemplateResponse)
async def update_email_template(
    template_id: int,
    data: EmailTemplateUpdate,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Update an email template."""
    template = await email_service.update_template(
        template_id,
        display_name=data.display_name,
        description=data.description,
        sendgrid_template_id=data.sendgrid_template_id,
        subject=data.subject,
        html_content=data.html_content,
        text_content=data.text_content,
        available_variables=data.available_variables,
        is_active=data.is_active
    )

    if not template:
        raise not_found("Template not found")

    return EmailTemplateResponse.model_validate(template)


@router.delete("/templates/{template_id}")
async def delete_email_template(
    template_id: int,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Delete an email template (system templates cannot be deleted)."""
    success, message = await email_service.delete_template(template_id)

    if not success:
        raise bad_request(message)

    return {"success": True, "message": message}


@router.post("/templates/{template_id}/preview", response_model=EmailPreviewResponse)
async def preview_email_template(
    template_id: int,
    data: EmailPreviewRequest,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Preview a template with sample data."""
    result = await email_service.preview_template(template_id, data.sample_data)

    if not result:
        raise not_found("Template not found")

    subject, html_content, text_content = result
    return EmailPreviewResponse(
        subject=subject,
        html_content=html_content,
        text_content=text_content
    )


@router.post("/templates/{template_id}/duplicate", response_model=EmailTemplateResponse)
async def duplicate_email_template(
    template_id: int,
    new_name: str = Query(..., description="Name for the duplicated template"),
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Duplicate an existing template."""
    # Check if new name already exists
    existing = await email_service.get_template_by_name(new_name)
    if existing:
        raise bad_request(f"Template with name '{new_name}' already exists")

    template = await email_service.duplicate_template(template_id, new_name)

    if not template:
        raise not_found("Template not found")

    return EmailTemplateResponse.model_validate(template)


# =============================================================================
# SendGrid Template Sync Endpoints
# =============================================================================

@router.get("/sendgrid/templates", response_model=SendGridTemplatesResponse)
async def list_sendgrid_templates(
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """
    List all dynamic templates from the connected SendGrid account.
    Returns basic info about each template without full content.
    """
    success, message, templates = await email_service.fetch_sendgrid_templates()

    return SendGridTemplatesResponse(
        success=success,
        message=message,
        templates=[SendGridTemplateItem(**t) for t in templates]
    )


@router.post("/sendgrid/import", response_model=ImportSendGridTemplateResponse)
async def import_sendgrid_template(
    data: ImportSendGridTemplateRequest,
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """
    Import a single SendGrid template into the local database.
    The template content will be fetched and stored locally.
    """
    success, message, template = await email_service.import_sendgrid_template(
        sendgrid_template_id=data.sendgrid_template_id,
        local_name=data.local_name,
        created_by_id=current_user.id
    )

    return ImportSendGridTemplateResponse(
        success=success,
        message=message,
        template=EmailTemplateResponse.model_validate(template) if template else None
    )


@router.post("/sendgrid/sync", response_model=SyncSendGridTemplatesResponse)
async def sync_sendgrid_templates(
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """
    Sync all SendGrid dynamic templates to the local database.
    Templates that already exist (based on SendGrid ID) will be skipped.
    """
    imported, skipped, failed, errors = await email_service.sync_sendgrid_templates(
        created_by_id=current_user.id
    )

    total = imported + skipped + failed
    return SyncSendGridTemplatesResponse(
        success=imported > 0 or (failed == 0 and total > 0),
        message=f"Imported {imported}, skipped {skipped}, failed {failed}",
        imported_count=imported,
        skipped_count=skipped,
        failed_count=failed,
        errors=errors
    )


# =============================================================================
# Analytics Endpoints
# =============================================================================

@router.get("/analytics", response_model=EmailAnalyticsResponse)
async def get_email_analytics(
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Get aggregated email analytics with delivery rates."""
    analytics = await email_service.get_analytics()
    return EmailAnalyticsResponse(**analytics)


@router.get("/analytics/daily", response_model=DailyStatsResponse)
async def get_daily_email_stats(
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Get daily email statistics for charting."""
    stats = await email_service.get_daily_stats(days)
    return DailyStatsResponse(
        stats=[DailyEmailStats(**s) for s in stats],
        period_days=days
    )


@router.get("/analytics/by-template", response_model=TemplateStatsResponse)
async def get_template_stats(
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Get email statistics grouped by template."""
    stats = await email_service.get_template_stats()
    return TemplateStatsResponse(
        templates=[TemplateStats(**s) for s in stats]
    )


# =============================================================================
# History Endpoint
# =============================================================================

@router.get("/history", response_model=EmailHistoryResponse)
async def get_email_history(
    search: Optional[str] = Query(None, description="Search by recipient email or name"),
    template_name: Optional[str] = Query(None, description="Filter by template name"),
    status: Optional[str] = Query(None, description="Filter by status (sent, delivered, opened, clicked, bounced)"),
    days: Optional[int] = Query(30, ge=1, le=365, description="Number of days to look back"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_admin_user),
    email_service: EmailService = Depends(get_email_service)
):
    """Get paginated email history with filters."""
    items, total = await email_service.get_email_history(
        search=search,
        template_name=template_name,
        status=status,
        days=days,
        page=page,
        page_size=page_size
    )

    _, total_pages = calculate_pagination(total, page, page_size)

    return EmailHistoryResponse(
        items=[EmailHistoryItem(**item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


# =============================================================================
# Legacy Endpoints (kept for backward compatibility)
# =============================================================================
