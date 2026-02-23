"""Instance Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class InstanceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider: str = Field(default="openstack")  # openstack, digitalocean

    # OpenStack fields (optional)
    flavor_id: Optional[str] = None
    network_id: Optional[str] = None

    # DigitalOcean fields (optional)
    size_slug: Optional[str] = None  # DO size slug (e.g., 's-1vcpu-1gb')
    region: Optional[str] = None  # DO region (e.g., 'nyc1')

    # Common fields
    image_id: Optional[str] = None
    key_name: Optional[str] = None
    cloud_init_template_id: Optional[int] = None
    license_product_id: Optional[int] = None
    event_id: Optional[int] = None
    assigned_to_user_id: Optional[int] = None
    ssh_public_key: Optional[str] = None


class InstanceBulkCreate(BaseModel):
    name_prefix: str = Field(..., min_length=1, max_length=200)
    count: int = Field(..., ge=1, le=50)
    provider: str = Field(default="openstack")  # openstack, digitalocean

    # OpenStack fields (optional)
    flavor_id: Optional[str] = None
    network_id: Optional[str] = None

    # DigitalOcean fields (optional)
    size_slug: Optional[str] = None
    region: Optional[str] = None

    # Common fields
    image_id: Optional[str] = None
    key_name: Optional[str] = None
    cloud_init_template_id: Optional[int] = None
    license_product_id: Optional[int] = None
    event_id: Optional[int] = None
    ssh_public_key: Optional[str] = None


class InstanceResponse(BaseModel):
    id: int
    name: str
    provider: str  # openstack, digitalocean
    provider_instance_id: Optional[str] = None
    status: str
    ip_address: Optional[str] = None
    vpn_ip: Optional[str] = None

    # OpenStack fields (optional)
    flavor_id: Optional[str] = None
    network_id: Optional[str] = None

    # DigitalOcean fields (optional)
    provider_size_slug: Optional[str] = None
    provider_region: Optional[str] = None

    # Common fields
    image_id: str
    key_name: Optional[str] = None
    cloud_init_template_id: Optional[int] = None
    license_product_id: Optional[int] = None
    event_id: Optional[int] = None
    event_name: Optional[str] = None  # Computed: event year + name
    assigned_to_user_id: Optional[int] = None
    error_message: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_by_username: Optional[str] = None  # Computed: creator's username

    # Participant self-service fields
    visibility: Optional[str] = "private"
    notes: Optional[str] = None
    instance_template_id: Optional[int] = None
    instance_template_name: Optional[str] = None  # Computed: template name

    created_at: datetime
    updated_at: datetime
    last_synced_at: Optional[datetime] = None  # Last successful status sync from provider

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
