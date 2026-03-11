"""Common dependency injection utilities."""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.participant_service import ParticipantService
from app.services.event_service import EventService
from app.services.email_service import EmailService
from app.services.vpn_service import VPNService
from app.services.openstack_service import OpenStackService
from app.services.digitalocean_service import DigitalOceanService
from app.services.instance_service import InstanceService
from app.services.cloud_init_service import CloudInitService
from app.services.license_service import LicenseService


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


async def get_openstack_service(
    db: AsyncSession = Depends(get_db)
) -> OpenStackService:
    """Get OpenStackService instance."""
    return OpenStackService(db)


async def get_cloud_init_service(
    db: AsyncSession = Depends(get_db)
) -> CloudInitService:
    """Get CloudInitService instance."""
    return CloudInitService(db)


async def get_license_service(
    db: AsyncSession = Depends(get_db)
) -> LicenseService:
    """Get LicenseService instance."""
    return LicenseService(db)


async def get_digitalocean_service(
    db: AsyncSession = Depends(get_db)
) -> DigitalOceanService:
    """Get DigitalOceanService instance."""
    return DigitalOceanService(db)


async def get_instance_service(
    db: AsyncSession = Depends(get_db)
) -> InstanceService:
    """Get InstanceService instance (provider-agnostic)."""
    return InstanceService(db)
