"""Response builder utilities for consistent API responses."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.event import EventParticipation
from app.models.vpn import VPNCredential
from app.schemas.auth import UserResponse
from app.schemas.event import EventParticipationResponse
from app.schemas.participant import ParticipantResponse, SponsorInfo


async def build_auth_user_response(
    user: User,
    db: AsyncSession,
    include_vpn_check: bool = True
) -> UserResponse:
    """
    Build UserResponse for authentication context (login, /me endpoint).

    This uses the simplified auth.UserResponse schema with has_vpn flag.

    Args:
        user: User model instance
        db: Database session
        include_vpn_check: Whether to check if user has VPN credentials

    Returns:
        UserResponse from app.schemas.auth
    """
    has_vpn = False

    if include_vpn_check:
        # Check if user has any VPN credentials
        vpn_result = await db.execute(
            select(func.count(VPNCredential.id))
            .where(VPNCredential.assigned_to_user_id == user.id)
        )
        vpn_count = vpn_result.scalar() or 0
        has_vpn = vpn_count > 0

    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        country=user.country,
        is_admin=user.is_admin,
        is_active=user.is_active,
        confirmed=user.confirmed,
        email_status=user.email_status,
        pandas_username=user.pandas_username,
        discord_username=user.discord_username,
        snowflake_id=user.snowflake_id,
        has_vpn=has_vpn
    )


async def build_participant_response(
    user: User,
    db: AsyncSession,
    include_sponsor: bool = True,
    include_vpn: bool = True
) -> ParticipantResponse:
    """
    Build ParticipantResponse for admin/sponsor context.

    This uses the comprehensive participant.ParticipantResponse schema with
    all tracking fields, VPN count, and SponsorInfo object.

    Args:
        user: User model instance
        db: Database session
        include_sponsor: Whether to include sponsor information
        include_vpn: Whether to check VPN count

    Returns:
        ParticipantResponse from app.schemas.participant
    """
    # Count VPN credentials assigned to this user
    vpn_count = 0
    if include_vpn:
        vpn_count_result = await db.execute(
            select(func.count(VPNCredential.id))
            .where(VPNCredential.assigned_to_user_id == user.id)
        )
        vpn_count = vpn_count_result.scalar() or 0

    # Build sponsor info if available
    sponsor_info = None
    if include_sponsor and user.sponsor_id:
        # Load sponsor relationship if not already loaded
        if not hasattr(user, 'sponsor') or user.sponsor is None:
            sponsor_result = await db.execute(
                select(User).where(User.id == user.sponsor_id)
            )
            sponsor = sponsor_result.scalar_one_or_none()
        else:
            sponsor = user.sponsor

        if sponsor:
            sponsor_info = SponsorInfo(
                id=sponsor.id,
                email=sponsor.email,
                first_name=sponsor.first_name,
                last_name=sponsor.last_name,
                full_name=f"{sponsor.first_name} {sponsor.last_name}"
            )

    return ParticipantResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        country=user.country,
        confirmed=user.confirmed,
        email_status=user.email_status,
        role=user.role,
        is_admin=user.is_admin,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        pandas_username=user.pandas_username,
        discord_username=user.discord_username,
        snowflake_id=user.snowflake_id,
        sponsor_email=user.sponsor_email,
        sponsor_id=user.sponsor_id,
        sponsor=sponsor_info,
        invite_sent=user.invite_sent,
        password_email_sent=user.password_email_sent,
        has_vpn=vpn_count > 0,
        vpn_count=vpn_count,
        # Participation tracking
        years_invited=user.years_invited,
        years_participated=user.years_participated,
        participation_rate=user.participation_rate,
        is_chronic_non_participant=user.is_chronic_non_participant,
        should_recommend_removal=user.should_recommend_removal,
        confirmed_at=user.confirmed_at
    )


async def build_event_participation_response(
    participation: EventParticipation,
    db: AsyncSession
) -> EventParticipationResponse:
    """
    Build EventParticipationResponse with user and event details.

    Args:
        participation: EventParticipation model instance
        db: Database session

    Returns:
        EventParticipationResponse with complete data
    """
    # Reload with relationships if not already loaded
    if not hasattr(participation, 'user') or participation.user is None:
        result = await db.execute(
            select(EventParticipation)
            .options(selectinload(EventParticipation.user))
            .options(selectinload(EventParticipation.event))
            .where(EventParticipation.id == participation.id)
        )
        p = result.scalar_one()
    else:
        p = participation

    return EventParticipationResponse(
        id=p.id,
        user_id=p.user_id,
        event_id=p.event_id,
        status=p.status,
        invited_at=p.invited_at,
        terms_accepted_at=p.terms_accepted_at,
        confirmed_at=p.confirmed_at,
        declined_at=p.declined_at,
        declined_reason=p.declined_reason,
        created_at=p.created_at,
        updated_at=p.updated_at,
        user_email=p.user.email if p.user else None,
        user_first_name=p.user.first_name if p.user else None,
        user_last_name=p.user.last_name if p.user else None,
        event_name=p.event.name if p.event else None,
        event_year=p.event.year if p.event else None
    )
