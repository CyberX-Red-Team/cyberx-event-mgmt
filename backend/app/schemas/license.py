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


class QueueReleaseRequest(BaseModel):
    slot_id: str
    result: str = "unknown"
    elapsed: int = 0


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
