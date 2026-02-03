"""Common dependency injection utilities."""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.participant_service import ParticipantService
from app.services.event_service import EventService
from app.services.email_service import EmailService
from app.services.vpn_service import VPNService


async def get_participant_service(
    db: AsyncSession = Depends(get_db)
) -> ParticipantService:
    """
    Get ParticipantService instance.

    Args:
        db: Database session from dependency injection

    Returns:
        Initialized ParticipantService
    """
    return ParticipantService(db)


async def get_event_service(
    db: AsyncSession = Depends(get_db)
) -> EventService:
    """
    Get EventService instance.

    Args:
        db: Database session from dependency injection

    Returns:
        Initialized EventService
    """
    return EventService(db)


async def get_email_service(
    db: AsyncSession = Depends(get_db)
) -> EmailService:
    """
    Get EmailService instance.

    Args:
        db: Database session from dependency injection

    Returns:
        Initialized EmailService
    """
    return EmailService(db)


async def get_vpn_service(
    db: AsyncSession = Depends(get_db)
) -> VPNService:
    """
    Get VPNService instance.

    Args:
        db: Database session from dependency injection

    Returns:
        Initialized VPNService
    """
    return VPNService(db)
