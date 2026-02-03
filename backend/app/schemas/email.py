"""Pydantic schemas for email operations."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field


# =============================================================================
# Email Template Schemas
# =============================================================================

class EmailTemplateCreate(BaseModel):
    """Schema for creating a new email template."""

    name: str = Field(..., min_length=1, max_length=100, description="Unique template identifier")
    display_name: str = Field(..., min_length=1, max_length=255, description="Human-readable name")
    description: Optional[str] = Field(None, description="Template description")
    sendgrid_template_id: Optional[str] = Field(None, max_length=100, description="SendGrid dynamic template ID (e.g., d-1234567890abcdef)")
    subject: str = Field(..., min_length=1, max_length=500, description="Email subject line")
    html_content: str = Field(..., min_length=1, description="HTML email body")
    text_content: Optional[str] = Field(None, description="Plain text email body")
    available_variables: List[str] = Field(default_factory=list, description="List of template variables")


class EmailTemplateUpdate(BaseModel):
    """Schema for updating an email template."""

    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    sendgrid_template_id: Optional[str] = Field(None, max_length=100)
    subject: Optional[str] = Field(None, min_length=1, max_length=500)
    html_content: Optional[str] = Field(None, min_length=1)
    text_content: Optional[str] = None
    available_variables: Optional[List[str]] = None
    is_active: Optional[bool] = None


class EmailTemplateResponse(BaseModel):
    """Schema for email template response."""

    id: int
    name: str
    display_name: str
    description: Optional[str]
    sendgrid_template_id: Optional[str]
    subject: str
    html_content: str
    text_content: Optional[str]
    available_variables: List[str]
    is_active: bool
    is_system: bool
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {
        "from_attributes": True
    }


class EmailTemplateListItem(BaseModel):
    """Simplified template for list views."""

    id: int
    name: str
    display_name: str
    description: Optional[str]
    sendgrid_template_id: Optional[str]
    is_active: bool
    is_system: bool
    created_at: datetime

    model_config = {
        "from_attributes": True
    }


class EmailPreviewRequest(BaseModel):
    """Request to preview a template with sample data."""

    sample_data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Sample data for preview")


class EmailPreviewResponse(BaseModel):
    """Rendered email preview."""

    subject: str
    html_content: str
    text_content: Optional[str]


# =============================================================================
# Email Sending Schemas
# =============================================================================

class SendEmailRequest(BaseModel):
    """Request to send email to a single recipient."""

    participant_id: int
    template_id: int = Field(..., description="ID of the template to use")
    custom_subject: Optional[str] = Field(None, description="Override the template subject")
    custom_variables: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional template variables")


class SendEmailResponse(BaseModel):
    """Response from sending an email."""

    success: bool
    message: str
    message_id: Optional[str] = None
    recipient_email: Optional[str] = None


class BulkEmailRequest(BaseModel):
    """Request to send bulk emails."""

    participant_ids: List[int]
    template_id: int = Field(..., description="ID of the template to use")
    custom_subject: Optional[str] = Field(None, description="Override the template subject")
    custom_variables: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional template variables")


class BulkEmailResponse(BaseModel):
    """Response from bulk email operation."""

    success: bool
    message: str
    sent_count: int
    failed_count: int
    failed_ids: List[int] = []
    errors: List[str] = []


class SendCustomEmailRequest(BaseModel):
    """Request to send a custom freeform email."""

    participant_ids: List[int]
    subject: str = Field(..., min_length=1, max_length=500)
    html_body: str = Field(..., min_length=1)
    text_body: Optional[str] = None


class SendTestEmailRequest(BaseModel):
    """Request to send a test email to verify SendGrid configuration."""

    to_email: str = Field(..., description="Email address to send test to")
    template_id: Optional[int] = Field(None, description="Optional template ID to test with")
    subject: Optional[str] = Field(None, description="Custom subject for test email")


class SendTestEmailResponse(BaseModel):
    """Response from sending a test email."""

    success: bool
    message: str
    message_id: Optional[str] = None
    to_email: str
    template_used: Optional[str] = None


# =============================================================================
# Email Analytics Schemas
# =============================================================================

class EmailAnalyticsResponse(BaseModel):
    """Aggregated email analytics with rates."""

    total_sent: int
    total_delivered: int
    total_opened: int
    total_clicked: int
    total_bounced: int
    total_spam_reports: int
    delivery_rate: float = Field(..., description="Percentage of emails delivered")
    open_rate: float = Field(..., description="Percentage of delivered emails opened")
    click_rate: float = Field(..., description="Percentage of opened emails clicked")
    bounce_rate: float = Field(..., description="Percentage of emails bounced")


class DailyEmailStats(BaseModel):
    """Daily email statistics."""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    sent: int
    delivered: int
    opened: int
    clicked: int
    bounced: int


class DailyStatsResponse(BaseModel):
    """Response containing daily stats."""

    stats: List[DailyEmailStats]
    period_days: int


class TemplateStats(BaseModel):
    """Statistics for a single template."""

    template_id: int
    template_name: str
    display_name: str
    sent: int
    delivered: int
    opened: int
    clicked: int
    bounced: int
    open_rate: float
    click_rate: float


class TemplateStatsResponse(BaseModel):
    """Response containing template statistics."""

    templates: List[TemplateStats]


# =============================================================================
# Email History Schemas
# =============================================================================

class EmailHistoryItem(BaseModel):
    """Single email history entry."""

    id: int
    recipient_email: str
    recipient_name: str
    template_name: Optional[str]
    subject: Optional[str]
    status: str = Field(..., description="Latest status: sent, delivered, opened, clicked, bounced")
    sent_at: datetime
    last_event_at: Optional[datetime]

    model_config = {
        "from_attributes": True
    }


class EmailHistoryResponse(BaseModel):
    """Paginated email history response."""

    items: List[EmailHistoryItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class EmailHistoryFilters(BaseModel):
    """Filters for email history query."""

    search: Optional[str] = Field(None, description="Search by recipient email or name")
    template_name: Optional[str] = Field(None, description="Filter by template name")
    status: Optional[str] = Field(None, description="Filter by status")
    days: Optional[int] = Field(30, description="Number of days to look back")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=100)


# =============================================================================
# Legacy Schemas (for backward compatibility)
# =============================================================================

class EmailTemplate(BaseModel):
    """Email template definition (legacy)."""

    name: str = Field(..., description="Template name: invite, password, reminder, survey, orientation")
    subject: str
    html_content: str
    text_content: Optional[str] = None


class EmailEventResponse(BaseModel):
    """Email event from SendGrid webhook."""

    id: int
    email: str
    event_type: str  # delivered, opened, clicked, bounced, etc.
    timestamp: datetime
    message_id: Optional[str] = None
    reason: Optional[str] = None

    model_config = {
        "from_attributes": True
    }


class EmailStatsResponse(BaseModel):
    """Email statistics (legacy)."""

    total_sent: int
    delivered: int
    opened: int
    clicked: int
    bounced: int
    spam_reports: int


class ParticipantEmailStatus(BaseModel):
    """Email status for a participant."""

    participant_id: int
    email: str
    invite_sent: Optional[datetime] = None
    password_email_sent: Optional[datetime] = None
    last_email_status: str
    events: List[EmailEventResponse] = []


# =============================================================================
# SendGrid Template Sync Schemas
# =============================================================================

class SendGridTemplateVersion(BaseModel):
    """SendGrid template version info."""

    id: str
    name: Optional[str] = None
    active: bool = False
    subject: Optional[str] = None
    updated_at: Optional[str] = None


class SendGridTemplateItem(BaseModel):
    """SendGrid template from API."""

    sendgrid_id: str
    name: str
    generation: str = "dynamic"
    updated_at: Optional[str] = None
    versions: List[SendGridTemplateVersion] = []


class SendGridTemplatesResponse(BaseModel):
    """Response from fetching SendGrid templates."""

    success: bool
    message: str
    templates: List[SendGridTemplateItem] = []


class SendGridTemplateDetail(BaseModel):
    """Detailed SendGrid template with content."""

    sendgrid_id: str
    name: str
    subject: str
    html_content: str
    plain_content: Optional[str] = None
    version_id: Optional[str] = None
    version_name: Optional[str] = None
    updated_at: Optional[str] = None


class ImportSendGridTemplateRequest(BaseModel):
    """Request to import a single SendGrid template."""

    sendgrid_template_id: str = Field(..., description="SendGrid template ID to import")
    local_name: Optional[str] = Field(None, description="Local name for the template (auto-generated if not provided)")


class ImportSendGridTemplateResponse(BaseModel):
    """Response from importing a SendGrid template."""

    success: bool
    message: str
    template: Optional[EmailTemplateResponse] = None


class SyncSendGridTemplatesResponse(BaseModel):
    """Response from syncing all SendGrid templates."""

    success: bool
    message: str
    imported_count: int
    skipped_count: int
    failed_count: int
    errors: List[str] = []
