"""Pydantic schemas for audit logging."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AuditLogResponse(BaseModel):
    """Audit log entry response."""

    id: int
    user_id: Optional[int]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[int]
    details: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime

    # User information (populated via join)
    user_email: Optional[str] = None
    user_name: Optional[str] = None

    model_config = {
        "from_attributes": True
    }


class AuditLogListResponse(BaseModel):
    """Response for audit log list with pagination."""

    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class AuditLogStats(BaseModel):
    """Audit log statistics."""

    total_events: int
    login_count: int
    logout_count: int
    user_create_count: int
    user_update_count: int
    user_delete_count: int
    role_change_count: int
    password_reset_count: int
    vpn_request_success_count: int
    vpn_request_failed_count: int
    vpn_request_rate_limited_count: int
    recent_24h: int
