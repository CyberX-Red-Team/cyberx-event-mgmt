"""Instance Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class InstanceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    flavor_id: Optional[str] = None
    image_id: Optional[str] = None
    network_id: Optional[str] = None
    key_name: Optional[str] = None
    cloud_init_template_id: Optional[int] = None
    event_id: Optional[int] = None
    assigned_to_user_id: Optional[int] = None
    ssh_public_key: Optional[str] = None


class InstanceBulkCreate(BaseModel):
    name_prefix: str = Field(..., min_length=1, max_length=200)
    count: int = Field(..., ge=1, le=50)
    flavor_id: Optional[str] = None
    image_id: Optional[str] = None
    network_id: Optional[str] = None
    key_name: Optional[str] = None
    cloud_init_template_id: Optional[int] = None
    event_id: Optional[int] = None
    ssh_public_key: Optional[str] = None


class InstanceResponse(BaseModel):
    id: int
    name: str
    openstack_id: Optional[str] = None
    status: str
    ip_address: Optional[str] = None
    flavor_id: str
    image_id: str
    network_id: str
    key_name: Optional[str] = None
    cloud_init_template_id: Optional[int] = None
    event_id: Optional[int] = None
    assigned_to_user_id: Optional[int] = None
    error_message: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InstanceListResponse(BaseModel):
    items: list[InstanceResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class InstanceStats(BaseModel):
    total: int
    active: int
    building: int
    error: int
    shutoff: int


class BulkDeleteRequest(BaseModel):
    instance_ids: list[int] = Field(..., min_length=1)


class BulkOperationResponse(BaseModel):
    success_count: int
    errors: list[str]
