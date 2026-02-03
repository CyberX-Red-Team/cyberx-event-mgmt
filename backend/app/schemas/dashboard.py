"""Pydantic schemas for admin dashboard."""
from pydantic import BaseModel
from app.schemas.participant import ParticipantStats
from app.schemas.vpn import VPNStats


class DashboardStats(BaseModel):
    """Combined dashboard statistics."""

    participants: ParticipantStats
    vpn: VPNStats


class RecentActivity(BaseModel):
    """Recent activity item for dashboard."""

    id: int
    type: str  # "participant_created", "vpn_assigned", "login", etc.
    description: str
    timestamp: str
    user_email: str | None = None


class DashboardResponse(BaseModel):
    """Full dashboard response."""

    stats: DashboardStats
    recent_participants: list = []
    recent_vpn_assignments: list = []
