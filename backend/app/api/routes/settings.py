"""System Settings API routes (Admin-only)."""
import logging
from typing import Optional, List
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db, get_current_admin_user
from app.api.exceptions import not_found, bad_request
from app.models.user import User
from app.models.app_setting import AppSetting

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/settings", tags=["System Settings (Admin)"])


class AppSettingResponse(BaseModel):
    """Response schema for app setting."""
    key: str
    value: Optional[str]
    description: Optional[str] = None


class AppSettingUpdate(BaseModel):
    """Schema for updating app setting."""
    value: str = Field(..., min_length=0)


class ProviderLimitUpdate(BaseModel):
    """Schema for updating provider limits."""
    openstack: int = Field(default=0, ge=0)
    digitalocean: int = Field(default=0, ge=0)


class ProviderLimitsResponse(BaseModel):
    """Response schema for provider limits."""
    openstack: int
    digitalocean: int


@router.get("/provider-limits", response_model=ProviderLimitsResponse)
async def get_provider_limits(
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get provider instance limits.

    Returns current max instances for each provider (0 = unlimited).
    """
    providers = ["openstack", "digitalocean"]
    limits = {}

    for provider in providers:
        setting_key = f"provider_max_instances_{provider}"
        result = await db.execute(
            select(AppSetting).where(AppSetting.key == setting_key)
        )
        setting = result.scalar_one_or_none()

        if setting and setting.value:
            try:
                limits[provider] = int(setting.value)
            except ValueError:
                limits[provider] = 0
        else:
            limits[provider] = 0

    return ProviderLimitsResponse(**limits)


@router.patch("/provider-limits", response_model=ProviderLimitsResponse)
async def update_provider_limits(
    data: ProviderLimitUpdate,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update provider instance limits.

    Set max instances for each provider (0 = unlimited).
    """
    providers_data = {
        "openstack": data.openstack,
        "digitalocean": data.digitalocean,
    }

    for provider, limit in providers_data.items():
        setting_key = f"provider_max_instances_{provider}"

        # Check if setting exists
        result = await db.execute(
            select(AppSetting).where(AppSetting.key == setting_key)
        )
        setting = result.scalar_one_or_none()

        if setting:
            # Update existing
            setting.value = str(limit)
        else:
            # Create new
            setting = AppSetting(
                key=setting_key,
                value=str(limit),
                description=f"Maximum instances allowed for {provider} provider (0 = unlimited)"
            )
            db.add(setting)

    await db.commit()

    logger.info(
        "Admin %s updated provider limits: OpenStack=%d, DigitalOcean=%d",
        current_user.email,
        data.openstack,
        data.digitalocean
    )

    return ProviderLimitsResponse(**providers_data)


@router.get("/all", response_model=List[AppSettingResponse])
async def get_all_settings(
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all app settings."""
    result = await db.execute(
        select(AppSetting).order_by(AppSetting.key)
    )
    settings = result.scalars().all()

    return [
        AppSettingResponse(
            key=s.key,
            value=s.value,
            description=s.description
        )
        for s in settings
    ]


@router.patch("/{key}", response_model=AppSettingResponse)
async def update_setting(
    key: str,
    data: AppSettingUpdate,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a specific app setting."""
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == key)
    )
    setting = result.scalar_one_or_none()

    if not setting:
        raise not_found("Setting", key)

    setting.value = data.value
    await db.commit()
    await db.refresh(setting)

    logger.info(
        "Admin %s updated setting %s = %s",
        current_user.email,
        key,
        data.value
    )

    return AppSettingResponse(
        key=setting.key,
        value=setting.value,
        description=setting.description
    )
