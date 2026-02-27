"""Admin API routes for Keycloak sync management."""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db, get_current_admin_user
from app.models.user import User
from app.models.password_sync_queue import PasswordSyncQueue
from app.services.keycloak_sync_service import KeycloakSyncService
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/keycloak", tags=["Admin - Keycloak"])


@router.get("/sync-status")
async def get_sync_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Get Keycloak sync queue statistics."""
    service = KeycloakSyncService(db)
    stats = await service.get_queue_stats()

    settings = get_settings()
    stats["sync_enabled"] = settings.PASSWORD_SYNC_ENABLED
    stats["keycloak_url"] = settings.KEYCLOAK_URL or "(not configured)"
    stats["keycloak_realm"] = settings.KEYCLOAK_REALM

    return stats


@router.post("/sync-now")
async def trigger_sync_now(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Manually trigger Keycloak sync processing."""
    settings = get_settings()

    if not settings.KEYCLOAK_URL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keycloak URL is not configured"
        )

    service = KeycloakSyncService(db)
    result = await service.process_sync_queue()

    return {
        "status": "ok",
        "synced": result["synced"],
        "failed": result["failed"],
        "skipped": result["skipped"]
    }


@router.post("/retry/{queue_id}")
async def retry_sync_entry(
    queue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Reset retry count for a failed sync entry to allow reprocessing."""
    result = await db.execute(
        select(PasswordSyncQueue).where(PasswordSyncQueue.id == queue_id)
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync queue entry not found"
        )

    entry.retry_count = 0
    entry.last_error = None
    await db.commit()

    return {"status": "ok", "message": f"Retry scheduled for queue entry {queue_id}"}


@router.get("/health")
async def check_keycloak_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Check if Keycloak is reachable."""
    service = KeycloakSyncService(db)
    healthy = await service.check_keycloak_health()

    settings = get_settings()

    return {
        "status": "healthy" if healthy else "unreachable",
        "keycloak_url": settings.KEYCLOAK_URL or "(not configured)",
        "keycloak_realm": settings.KEYCLOAK_REALM,
        "sync_enabled": settings.PASSWORD_SYNC_ENABLED
    }
