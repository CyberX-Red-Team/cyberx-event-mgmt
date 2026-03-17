"""Admin routes for managing service API keys."""
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_permission
from app.models.service_api_key import ServiceAPIKey, generate_api_key
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/api-keys",
    tags=["Admin - API Keys"],
)


# ─── Schemas ──────────────────────────────────────────────────────────

class CreateAPIKeyRequest(BaseModel):
    name: str
    scopes: list[str] = []
    expires_at: datetime | None = None


class CreateAPIKeyResponse(BaseModel):
    id: int
    name: str
    key: str  # plaintext — shown once only
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None


class APIKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    last_used_at: datetime | None
    last_used_ip: str | None
    created_at: datetime | None
    expires_at: datetime | None


# ─── Routes ───────────────────────────────────────────────────────────

@router.post("", response_model=CreateAPIKeyResponse, status_code=201)
async def create_api_key(
    body: CreateAPIKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("admin.manage_settings")),
):
    """Create a new service API key. The plaintext key is returned once."""
    raw_key = generate_api_key()
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    api_key = ServiceAPIKey(
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info(
        "API key created: id=%s name='%s' by user_id=%s",
        api_key.id, api_key.name, current_user.id,
    )

    return CreateAPIKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key=raw_key,
        key_prefix=key_prefix,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("admin.manage_settings")),
):
    """List all service API keys (without secrets)."""
    result = await db.execute(
        select(ServiceAPIKey).order_by(ServiceAPIKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        APIKeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes or [],
            is_active=k.is_active,
            last_used_at=k.last_used_at,
            last_used_ip=k.last_used_ip,
            created_at=k.created_at,
            expires_at=k.expires_at,
        )
        for k in keys
    ]


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("admin.manage_settings")),
):
    """Revoke (deactivate) a service API key."""
    result = await db.execute(
        select(ServiceAPIKey).where(ServiceAPIKey.id == key_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    api_key.is_active = False
    await db.commit()

    logger.info(
        "API key revoked: id=%s name='%s' by user_id=%s",
        api_key.id, api_key.name, current_user.id,
    )
