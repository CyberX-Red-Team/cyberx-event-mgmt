"""Pydantic schemas for event and participation management."""
from datetime import datetime, date
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field


class ParticipationStatusEnum(str, Enum):
    """Participation status for API."""
    INVITED = "invited"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    NO_RESPONSE = "no_response"


class EventBase(BaseModel):
    """Base event schema."""
    year: int = Field(..., ge=2020, le=2100)
    name: str = Field(..., min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=1, max_length=255, description="URL-friendly identifier (auto-generated from name if not provided)")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    event_time: Optional[str] = Field(None, max_length=255)
    event_location: Optional[str] = Field(None, max_length=255)
    terms_version: Optional[str] = Field(None, max_length=50)
    terms_content: Optional[str] = None


class EventCreate(EventBase):
    """Schema for creating an event."""
    is_active: bool = False


class EventUpdate(BaseModel):
    """Schema for updating an event."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=1, max_length=255, description="URL-friendly identifier")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    event_time: Optional[str] = Field(None, max_length=255)
    event_location: Optional[str] = Field(None, max_length=255)
    terms_version: Optional[str] = Field(None, max_length=50)
    terms_content: Optional[str] = None
    is_active: Optional[bool] = None
    vpn_available: Optional[bool] = None
    test_mode: Optional[bool] = None
    ssh_public_key: Optional[str] = None
    ssh_private_key: Optional[str] = None
    discord_channel_id: Optional[str] = Field(None, max_length=100, description="Discord channel ID for invite generation")


class EventResponse(BaseModel):
    """Event response schema."""
    id: int
    year: int
    name: str
    slug: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    event_time: Optional[str] = None
    event_location: Optional[str] = None
    terms_version: Optional[str] = None
    is_active: bool
    vpn_available: bool = False
    test_mode: bool = False
    ssh_public_key: Optional[str] = None
    discord_channel_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Statistics
    total_invited: int = 0
    total_confirmed: int = 0
    total_declined: int = 0
    total_no_response: int = 0

    model_config = {
        "from_attributes": True
    }


class EventListResponse(BaseModel):
    """Response for event list."""
    items: List[EventResponse]
    total: int


class EventParticipationBase(BaseModel):
    """Base event participation schema."""
    user_id: int
    event_id: int
    status: ParticipationStatusEnum = ParticipationStatusEnum.INVITED


class EventParticipationCreate(EventParticipationBase):
    """Schema for creating event participation."""
    pass


class EventParticipationUpdate(BaseModel):
    """Schema for updating event participation."""
    status: Optional[ParticipationStatusEnum] = None
    terms_accepted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    declined_at: Optional[datetime] = None
    declined_reason: Optional[str] = None


class ParticipantBrief(BaseModel):
    """Brief participant info for participation responses."""
    id: int
    email: str
    first_name: str
    last_name: str
    full_name: str

    model_config = {
        "from_attributes": True
    }


class EventParticipationResponse(BaseModel):
    """Event participation response schema."""
    id: int
    user_id: int
    event_id: int
    status: str
    invited_at: datetime
    terms_accepted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    declined_at: Optional[datetime] = None
    declined_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Discord invite
    discord_invite_code: Optional[str] = None

    # Related entities (populated when needed)
    user: Optional[ParticipantBrief] = None
    event_year: Optional[int] = None
    event_name: Optional[str] = None

    model_config = {
        "from_attributes": True
    }


class EventParticipationListResponse(BaseModel):
    """Response for event participation list with pagination."""
    items: List[EventParticipationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class BulkInviteRequest(BaseModel):
    """Request to bulk invite users to an event."""
    event_id: int
    user_ids: List[int]


class BulkInviteResponse(BaseModel):
    """Response for bulk invite operation."""
    success: bool
    message: str
    invited_count: int
    already_invited_count: int
    failed_ids: List[int] = []


class ConfirmParticipationRequest(BaseModel):
    """Request for a user to confirm participation."""
    event_id: int
    accept_terms: bool = True


class ConfirmParticipationResponse(BaseModel):
    """Response for participation confirmation."""
    success: bool
    message: str
    participation: Optional[EventParticipationResponse] = None


class ParticipationHistoryResponse(BaseModel):
    """User's participation history across all events."""
    user_id: int
    total_years_invited: int
    total_years_participated: int
    participation_rate: float
    is_chronic_non_participant: bool
    should_recommend_removal: bool
    history: List[EventParticipationResponse]


class SSHKeyPairResponse(BaseModel):
    """Response containing SSH key pair."""
    public_key: str
    private_key: str


class EventSSHPrivateKeyResponse(BaseModel):
    """Response for event SSH private key (accessible by participants)."""
    event_id: int
    event_name: str
    ssh_private_key: Optional[str] = None
    has_ssh_key: bool  # Whether the event has SSH keys configured
