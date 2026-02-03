"""Pydantic schemas for participant management."""
from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, EmailStr, Field


class UserRoleEnum(str, Enum):
    """User role enumeration for API."""
    ADMIN = "admin"
    SPONSOR = "sponsor"
    INVITEE = "invitee"  # Invited to participate - becomes participant when confirmed


class SponsorInfo(BaseModel):
    """Brief sponsor information for participant responses."""
    id: int
    email: str
    first_name: str
    last_name: str
    full_name: str

    model_config = {
        "from_attributes": True
    }


class ParticipantBase(BaseModel):
    """Base participant schema."""

    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    country: str = Field(default="USA", max_length=100)


class ParticipantCreate(ParticipantBase):
    """Schema for creating a participant."""

    confirmed: str = Field(default="UNKNOWN")
    pandas_username: Optional[str] = None
    pandas_password: Optional[str] = None
    discord_username: Optional[str] = None
    sponsor_email: Optional[EmailStr] = None
    sponsor_id: Optional[int] = None
    role: UserRoleEnum = UserRoleEnum.INVITEE
    is_admin: bool = False  # Legacy support


class ParticipantUpdate(BaseModel):
    """Schema for updating a participant."""

    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, min_length=1, max_length=255)
    last_name: Optional[str] = Field(None, min_length=1, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    confirmed: Optional[str] = None
    email_status: Optional[str] = None
    future_participation: Optional[str] = None
    remove_permanently: Optional[str] = None
    pandas_username: Optional[str] = None
    pandas_password: Optional[str] = None
    discord_username: Optional[str] = None
    snowflake_id: Optional[str] = None
    sponsor_email: Optional[EmailStr] = None
    sponsor_id: Optional[int] = None
    role: Optional[UserRoleEnum] = None
    is_admin: Optional[bool] = None  # Legacy support
    is_active: Optional[bool] = None


class ParticipantResponse(BaseModel):
    """Participant response schema."""

    id: int
    email: EmailStr
    first_name: str
    last_name: str
    country: str
    confirmed: str
    email_status: str
    role: str
    is_admin: bool  # Legacy field
    is_active: bool
    created_at: datetime
    updated_at: datetime

    # Optional fields
    pandas_username: Optional[str] = None
    discord_username: Optional[str] = None
    snowflake_id: Optional[str] = None
    sponsor_email: Optional[str] = None
    sponsor_id: Optional[int] = None

    # Sponsor details (populated when available)
    sponsor: Optional[SponsorInfo] = None

    # Email tracking
    invite_sent: Optional[datetime] = None
    password_email_sent: Optional[datetime] = None

    # VPN status
    has_vpn: bool = False
    vpn_count: int = 0

    # Participation tracking
    years_invited: int = 0
    years_participated: int = 0
    participation_rate: float = 0.0
    is_chronic_non_participant: bool = False
    should_recommend_removal: bool = False
    confirmed_at: Optional[datetime] = None  # From audit log PARTICIPATION_CONFIRM

    model_config = {
        "from_attributes": True
    }


class ParticipantListResponse(BaseModel):
    """Response for participant list with pagination."""

    items: List[ParticipantResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ParticipantStats(BaseModel):
    """Invitee/participant statistics for admin dashboard."""

    total_invitees: int
    confirmed_count: int  # Confirmed for current year
    unconfirmed_count: int
    with_vpn_count: int
    without_vpn_count: int
    active_count: int
    inactive_count: int
    admin_count: int = 0
    sponsor_count: int = 0
    invitee_count: int = 0  # Regular invitees (not admin/sponsor)
    chronic_non_participant_count: int = 0  # Invited 3+ years, never participated
    recommended_removal_count: int = 0  # Based on participation history


class BulkActionRequest(BaseModel):
    """Request for bulk operations on participants."""

    participant_ids: List[int]
    action: str = Field(..., description="Action to perform: activate, deactivate, delete, send_invite, send_password")


class BulkActionResponse(BaseModel):
    """Response for bulk operations."""

    success: bool
    message: str
    affected_count: int
    failed_ids: List[int] = []


class PasswordResetRequest(BaseModel):
    """Request to reset a participant's password."""

    participant_id: int
    send_email: bool = True


class PasswordResetResponse(BaseModel):
    """Response for password reset."""

    success: bool
    message: str
    new_password: Optional[str] = None  # Only returned if send_email is False


class RoleUpdateRequest(BaseModel):
    """Request to update a user's role."""

    participant_id: int
    role: UserRoleEnum


class SponsorAssignRequest(BaseModel):
    """Request to assign a sponsor to a participant."""

    participant_id: int
    sponsor_id: int


class MySponsoredParticipantsResponse(BaseModel):
    """Response for a sponsor's participants list."""

    items: List[ParticipantResponse]
    total: int


class SponsorInviteeListResponse(BaseModel):
    """Response for sponsor's invitee list with pagination."""

    items: List[ParticipantResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class SponsorInviteeStats(BaseModel):
    """Statistics for sponsor's invitees."""

    total_invitees: int
    confirmed_count: int
    unconfirmed_count: int
    with_vpn_count: int
    without_vpn_count: int
    active_count: int
    inactive_count: int


class InviteeCreateRequest(BaseModel):
    """Sponsor creates invitee - no sponsor_id field (auto-assigned)."""

    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    country: str = Field(default="USA", max_length=100)
    confirmed: str = Field(default="UNKNOWN")
    discord_username: Optional[str] = None


class InviteeUpdateRequest(BaseModel):
    """
    Sponsor updates invitee - limited fields only.

    EXCLUDED fields (sponsors cannot change):
    - role, sponsor_id, pandas_username, is_admin, email_status
    """

    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, min_length=1, max_length=255)
    last_name: Optional[str] = Field(None, min_length=1, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    confirmed: Optional[str] = None
    discord_username: Optional[str] = None
