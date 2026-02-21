"""License management Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Product schemas ─────────────────────────────────────────

class LicenseProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    license_blob: str = Field(..., min_length=1)
    max_concurrent: int = Field(default=2, ge=1, le=100)
    slot_ttl: int = Field(default=7200, ge=60)
    token_ttl: int = Field(default=7200, ge=60)
    download_filename: Optional[str] = None


class LicenseProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    license_blob: Optional[str] = None
    max_concurrent: Optional[int] = Field(None, ge=1, le=100)
    slot_ttl: Optional[int] = Field(None, ge=60)
    token_ttl: Optional[int] = Field(None, ge=60)
    download_filename: Optional[str] = None
    is_active: Optional[bool] = None


class LicenseProductResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    max_concurrent: int
    slot_ttl: int
    token_ttl: int
    download_filename: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LicenseProductDetailResponse(LicenseProductResponse):
    license_blob: str


class LicenseProductListResponse(BaseModel):
    items: list[LicenseProductResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── Queue schemas ───────────────────────────────────────────

class QueueAcquireRequest(BaseModel):
    product_id: int
    hostname: Optional[str] = None
    ip_address: Optional[str] = None


class QueueReleaseRequest(BaseModel):
    slot_id: str
    result: str = "unknown"
    elapsed_seconds: int = 0


class LicenseQueueStatus(BaseModel):
    product_id: int
    product_name: str
    active_slots: int
    max_concurrent: int
    recent_completions: list[dict]


class LicenseStats(BaseModel):
    total_tokens_generated: int
    tokens_used: int
    tokens_expired: int
    active_slots: int
    total_products: int
    active_products: int
    products: list[dict]  # Per-product breakdown


# ── Token schemas ───────────────────────────────────────────

class LicenseTokenResponse(BaseModel):
    """Token details (admin view)."""
    id: int
    product_id: int
    used: bool
    used_at: Optional[datetime] = None
    used_by_ip: Optional[str] = None
    instance_id: Optional[int] = None
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class LicenseTokenCreateResponse(BaseModel):
    """Response when generating a new token (only time raw token is visible)."""
    token: str
    product_id: int
    expires_at: datetime


class LicenseBlobResponse(BaseModel):
    """Response from GET /api/license/blob (VM-facing endpoint)."""
    license_blob: str
    product_name: str


# ── Queue response schemas ──────────────────────────────────

class QueueAcquireResponse(BaseModel):
    """Response from POST /api/license/queue/acquire."""
    status: str  # "granted" or "wait"
    slot_id: Optional[str] = None
    position: Optional[int] = None
    message: Optional[str] = None


class QueueReleaseResponse(BaseModel):
    """Response from POST /api/license/queue/release."""
    status: str
    message: str


class LicenseSlotResponse(BaseModel):
    """Slot details (admin view)."""
    id: int
    slot_id: str
    product_id: int
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    acquired_at: datetime
    released_at: Optional[datetime] = None
    result: Optional[str] = None
    elapsed_seconds: Optional[int] = None
    is_active: bool

    model_config = {"from_attributes": True}
