"""Email workflow schemas."""
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class WorkflowBase(BaseModel):
    """Base workflow schema."""
    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    trigger_event: str = Field(..., min_length=1, max_length=100)
    template_name: str = Field(..., min_length=1, max_length=100)
    priority: int = Field(default=5, ge=1, le=10)
    custom_vars: Optional[Dict[str, Any]] = None
    delay_minutes: Optional[int] = Field(default=None, ge=0)
    is_enabled: bool = True


class WorkflowCreate(WorkflowBase):
    """Schema for creating a workflow."""
    pass


class WorkflowUpdate(BaseModel):
    """Schema for updating a workflow."""
    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    trigger_event: Optional[str] = Field(None, min_length=1, max_length=100)
    template_name: Optional[str] = Field(None, min_length=1, max_length=100)
    priority: Optional[int] = Field(None, ge=1, le=10)
    custom_vars: Optional[Dict[str, Any]] = None
    delay_minutes: Optional[int] = Field(None, ge=0)
    is_enabled: Optional[bool] = None


class WorkflowResponse(WorkflowBase):
    """Schema for workflow response."""
    id: int
    is_system: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    created_by_id: Optional[int] = None

    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    """Schema for paginated workflow list."""
    items: list[WorkflowResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TriggerEventInfo(BaseModel):
    """Information about a trigger event."""
    event: str
    display_name: str
    description: str
    available_variables: list[str]


class TriggerEventsResponse(BaseModel):
    """Schema for available trigger events."""
    events: list[TriggerEventInfo]
