"""Admin API routes for Keycloak sync management."""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db, get_current_admin_user
from app.models.user import User
from app.models.password_sync_queue import PasswordSyncQueue, SyncOperation
from app.services.keycloak_sync_service import KeycloakSyncService
from app.config import get_settings
from app.utils.encryption import encrypt_field

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


@router.post("/sync-user/{user_id}")
async def sync_single_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Queue and immediately sync a single confirmed user to Keycloak."""
    settings = get_settings()
    if not settings.KEYCLOAK_URL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keycloak URL is not configured"
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.pandas_username or not user.pandas_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no credentials to sync (not yet confirmed)"
        )

    # Queue (upsert) a sync entry
    service = KeycloakSyncService(db)
    await service.queue_user_sync(
        user_id=user.id,
        username=user.pandas_username,
        password=user.pandas_password,
        operation=SyncOperation.CREATE_USER
    )
    await db.commit()

    # Immediately process the queue
    sync_result = await service.process_sync_queue()

    return {
        "status": "ok",
        "user_id": user_id,
        "username": user.pandas_username,
        "synced": sync_result["synced"],
        "failed": sync_result["failed"],
        "skipped": sync_result["skipped"]
    }


class BulkSyncRequest(BaseModel):
    user_ids: List[int] = []  # Empty = all unsynced confirmed users


@router.post("/sync-confirmed")
async def sync_confirmed_users(
    request: BulkSyncRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """
    Queue and sync confirmed users to Keycloak.

    If user_ids is provided, syncs only those users.
    If user_ids is empty, syncs all confirmed users who aren't yet synced.
    """
    settings = get_settings()
    if not settings.KEYCLOAK_URL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keycloak URL is not configured"
        )

    # Build query for users with credentials
    query = select(User).where(
        User.pandas_username.isnot(None),
        User._pandas_password_encrypted.isnot(None),
    )

    if request.user_ids:
        query = query.where(User.id.in_(request.user_ids))
    else:
        # Only unsynced users when doing bulk all
        query = query.where(User.keycloak_synced == False)

    result = await db.execute(query)
    users = result.scalars().all()

    if not users:
        return {
            "status": "ok",
            "queued": 0,
            "message": "No users to sync"
        }

    # Queue sync entries for each user
    service = KeycloakSyncService(db)
    queued = 0
    for user in users:
        await service.queue_user_sync(
            user_id=user.id,
            username=user.pandas_username,
            password=user.pandas_password,
            operation=SyncOperation.CREATE_USER
        )
        queued += 1

    await db.commit()

    # Process the queue
    sync_result = await service.process_sync_queue()

    return {
        "status": "ok",
        "queued": queued,
        "synced": sync_result["synced"],
        "failed": sync_result["failed"],
        "skipped": sync_result["skipped"]
    }
