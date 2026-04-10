"""Pydantic schemas for VPN management."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class VPNCredentialBase(BaseModel):
    """Base VPN credential schema."""

    endpoint: str = Field(..., description="VPN server endpoint (ip:port)")


class VPNCredentialResponse(BaseModel):
    """VPN credential response schema."""

    id: int
    interface_ip: str
    ipv4_address: Optional[str]
    endpoint: str
    assignment_type: str = "USER_REQUESTABLE"
    file_hash: Optional[str] = None
    request_batch_id: Optional[str] = None
    is_available: bool
    assigned_to_user_id: Optional[int]
    assigned_at: Optional[datetime]
    created_at: datetime

    # Assigned user info (if assigned to user)
    assigned_to_email: Optional[str] = None
    assigned_to_name: Optional[str] = None

    # Assigned instance info (if assigned to instance)
    assigned_to_instance_id: Optional[int] = None
    assigned_instance_at: Optional[datetime] = None
    assigned_instance_name: Optional[str] = None
    assigned_instance_created_by_email: Optional[str] = None
    assigned_instance_created_by_name: Optional[str] = None

    model_config = {
        "from_attributes": True
    }


class VPNCredentialListResponse(BaseModel):
    """Response for VPN credential list with pagination."""

    items: List[VPNCredentialResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class VPNStats(BaseModel):
    """VPN statistics for admin dashboard."""

    total_credentials: int
    available_count: int
    assigned_count: int


class VPNAssignRequest(BaseModel):
    """Request to assign VPN to a participant."""

    participant_id: int
    count: int = Field(default=1, ge=1, le=25, description="Number of VPNs to assign (max 25)")


class VPNAssignResponse(BaseModel):
    """Response for VPN assignment."""

    success: bool
    message: str
    assigned_count: int = 0
    participant_id: Optional[int] = None


class VPNConfigResponse(BaseModel):
    """WireGuard configuration file content."""

    config: str
    filename: str


class VPNBulkAssignRequest(BaseModel):
    """Request to bulk assign VPN to multiple participants."""

    participant_ids: List[int]
    count_per_participant: int = Field(default=1, ge=1, le=25, description="VPNs per participant (max 25)")


class VPNBulkAssignResponse(BaseModel):
    """Response for bulk VPN assignment."""

    success: bool
    message: str
    assigned_count: int
    failed_ids: List[int] = []
    errors: List[str] = []


class VPNRequestRequest(BaseModel):
    """Request for participant to request VPN credentials."""

    count: int = Field(default=1, ge=1, le=25, description="Number of VPNs to request (max 25)")


class VPNRequestResponse(BaseModel):
    """Response for participant VPN request."""

    success: bool
    message: str
    assigned_count: int
    total_vpns: int  # Total VPNs user now has


class VPNImportResponse(BaseModel):
    """Response from queueing a VPN bulk import job.

    The actual import runs asynchronously in a background task. Clients
    should poll ``GET /api/vpn/import-jobs/{job_id}`` for progress and the
    final imported/skipped counts.
    """

    success: bool
    message: str
    job_id: int
    status: str


class VPNImportJobResponse(BaseModel):
    """Detailed status of a VPN import job."""

    id: int
    status: str  # pending | processing | completed | failed
    filename: Optional[str] = None
    file_size_bytes: int
    assignment_type: str
    endpoint_override: Optional[str] = None

    total_files: Optional[int] = None
    processed_files: int
    imported_count: int
    skipped_count: int
    error_count: int
    errors: List[str] = []

    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_by_user_id: Optional[int] = None


class VPNImportJobListResponse(BaseModel):
    """List of recent VPN import jobs."""

    items: List[VPNImportJobResponse]
    total: int


class VPNMyCredentialsResponse(BaseModel):
    """Response for participant's own VPN credentials."""

    credentials: List[VPNCredentialResponse]
    total: int


class VPNBulkDeleteRequest(BaseModel):
    """Request to bulk delete VPN credentials."""

    vpn_ids: List[int] = Field(..., description="List of VPN credential IDs to delete")


class VPNBulkDeleteResponse(BaseModel):
    """Response for bulk VPN deletion."""

    success: bool
    message: str
    deleted_count: int
    failed_ids: List[int] = []
    errors: List[str] = []


class VPNRequestBatch(BaseModel):
    """VPN request batch information."""

    batch_id: str
    requested_at: datetime
    count: int


class VPNRequestBatchesResponse(BaseModel):
    """Response for user's VPN request batches."""

    batches: List[VPNRequestBatch]
    total_batches: int


class VPNUpdateAssignmentTypeRequest(BaseModel):
    """Request to update VPN assignment type."""

    assignment_type: str = Field(..., description="USER_REQUESTABLE | INSTANCE_AUTO_ASSIGN | RESERVED")


class VPNUpdateAssignmentTypeResponse(BaseModel):
    """Response for VPN assignment type update."""

    success: bool
    message: str
    vpn_id: int
    new_assignment_type: str


class VPNBulkUpdateAssignmentTypeRequest(BaseModel):
    """Request to bulk update VPN assignment types."""

    vpn_ids: List[int] = Field(..., description="List of VPN credential IDs")
    assignment_type: str = Field(..., description="USER_REQUESTABLE | INSTANCE_AUTO_ASSIGN | RESERVED")


class VPNBulkUpdateAssignmentTypeResponse(BaseModel):
    """Response for bulk VPN assignment type update."""

    success: bool
    message: str
    success_count: int
    skipped_count: int
    errors: List[str] = []


class VPNInstancePoolStats(BaseModel):
    """Statistics for INSTANCE_AUTO_ASSIGN VPN pool."""

    total: int = Field(..., description="Total INSTANCE_AUTO_ASSIGN VPNs")
    available: int = Field(..., description="Available INSTANCE_AUTO_ASSIGN VPNs")
    assigned: int = Field(..., description="Assigned INSTANCE_AUTO_ASSIGN VPNs")
