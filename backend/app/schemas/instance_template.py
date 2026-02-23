"""Instance Template Pydantic schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class InstanceTemplateCreate(BaseModel):
    """Schema for creating instance templates."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    provider: str = Field(default="openstack")

    # OpenStack fields
    flavor_id: Optional[str] = None
    network_id: Optional[str] = None

    # DigitalOcean fields
    provider_size_slug: Optional[str] = None
    provider_region: Optional[str] = None

    # Common
    image_id: str
    cloud_init_template_id: Optional[int] = None
    license_product_id: Optional[int] = None
    event_id: int
    max_instances: int = Field(default=0, ge=0)


class InstanceTemplateUpdate(BaseModel):
    """Schema for updating instance templates."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    max_instances: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class InstanceTemplateResponse(BaseModel):
    """Schema for instance template responses."""
    id: int
    name: str
    description: Optional[str]
    provider: str
    flavor_id: Optional[str]
    network_id: Optional[str]
    provider_size_slug: Optional[str]
    provider_region: Optional[str]
    image_id: str
    cloud_init_template_id: Optional[int]
    cloud_init_template_name: Optional[str] = None  # Computed
    license_product_id: Optional[int]
    license_product_name: Optional[str] = None  # Computed
    event_id: int
    event_name: Optional[str] = None  # Computed
    max_instances: int
    current_instance_count: int = 0  # Computed
    created_by_user_id: Optional[int]
    created_by_username: Optional[str] = None  # Computed
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InstanceTemplateListResponse(BaseModel):
    """Schema for paginated template list responses."""
    items: list[InstanceTemplateResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class InstanceFromTemplateRequest(BaseModel):
    """Schema for provisioning instance from template."""
    template_id: int
    name: str = Field(..., min_length=1, max_length=255)
    visibility: str = Field(default="private", pattern="^(private|public)$")
    notes: Optional[str] = None
