"""Cloud-init VPN configuration API routes."""
import logging
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.api.exceptions import unauthorized, not_found
from app.api.utils.dependencies import get_vpn_service
from app.models.instance import Instance
from app.services.vpn_service import VPNService
from app.schemas.cloud_init import CloudInitVPNConfigResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cloud-init", tags=["Cloud-Init"])


def _extract_bearer_token(authorization: str) -> str:
    """Extract Bearer token from Authorization header."""
    if not authorization:
        raise unauthorized("Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise unauthorized("Invalid Authorization header format. Expected: Bearer <token>")

    return parts[1]


@router.get("/vpn-config", response_model=CloudInitVPNConfigResponse)
async def get_instance_vpn_config(
    request: Request,
    authorization: str = Header(...),
    service: VPNService = Depends(get_vpn_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve VPN configuration for instance using token-based authentication.

    This endpoint is called by cloud-init during instance provisioning to fetch
    the assigned VPN configuration.

    Security:
    - Token is single-use (deleted after retrieval)
    - 3-minute expiry window
    - SHA-256 hash stored in database
    - No session/cookie auth required

    Args:
        authorization: Bearer token from cloud-init
        service: VPN service dependency
        db: Database session

    Returns:
        CloudInitVPNConfigResponse with VPN configuration

    Raises:
        401: Invalid or expired token
        404: No VPN assigned to instance
    """
    # Extract Bearer token
    raw_token = _extract_bearer_token(authorization)

    # Hash token to match database
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    # Find instance with matching token
    result = await db.execute(
        select(Instance)
        .where(Instance.vpn_config_token == token_hash)
    )
    instance = result.scalar_one_or_none()

    if not instance:
        logger.warning("VPN config request with invalid token from IP: %s", request.client.host if request.client else "unknown")
        raise unauthorized("Invalid or expired VPN config token")

    # Check token expiry
    if instance.vpn_config_token_expires_at is None:
        logger.error("Instance %d has token but no expiry time", instance.id)
        raise unauthorized("VPN config token expired")

    if instance.vpn_config_token_expires_at < datetime.now(timezone.utc):
        logger.warning("Expired VPN config token for instance %d (expired at %s)",
                      instance.id, instance.vpn_config_token_expires_at)
        raise unauthorized("VPN config token expired")

    # Get assigned VPN
    vpn = await service.get_instance_vpn(instance.id)
    if not vpn:
        logger.error("Instance %d has valid token but no VPN assigned", instance.id)
        raise not_found("No VPN assigned to this instance")

    # Generate WireGuard config
    config = service.generate_wireguard_config(vpn)

    logger.info("VPN config retrieved by instance %d (name: %s) from IP: %s",
               instance.id, instance.name, request.client.host if request.client else "unknown")

    # Mark token as consumed (one-time use)
    instance.vpn_config_token = None
    instance.vpn_config_token_expires_at = None
    await db.commit()

    logger.info("VPN config token consumed for instance %d", instance.id)

    return CloudInitVPNConfigResponse(
        config=config,
        ipv4_address=vpn.ipv4_address or "",
        interface_ip=vpn.interface_ip,
        endpoint=vpn.endpoint
    )
