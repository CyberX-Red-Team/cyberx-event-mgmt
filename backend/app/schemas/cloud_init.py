"""Cloud-init template Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CloudInitTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    content: str = Field(..., min_length=1)
    is_default: bool = False


class CloudInitTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    content: Optional[str] = None
    is_default: Optional[bool] = None


class CloudInitTemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    content: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CloudInitTemplateListResponse(BaseModel):
    items: list[CloudInitTemplateResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class CloudInitPreviewRequest(BaseModel):
    variables: dict = Field(default_factory=dict)


class CloudInitPreviewResponse(BaseModel):
    rendered: str
