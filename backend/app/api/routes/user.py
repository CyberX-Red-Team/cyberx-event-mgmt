"""User preference routes."""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.api.dependencies import get_current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/user",
    tags=["user"],
)


class ThemePreferenceRequest(BaseModel):
    """Request model for updating theme preference."""
    theme: str = Field(..., pattern="^(light|dark)$", description="Theme preference: 'light' or 'dark'")


class ThemePreferenceResponse(BaseModel):
    """Response model for theme preference."""
    theme: str


@router.get("/theme", response_model=ThemePreferenceResponse)
async def get_theme_preference(
    current_user: User = Depends(get_current_active_user),
):
    """
    Get current user's theme preference.

    Returns:
        Theme preference ('light' or 'dark')
    """
    return ThemePreferenceResponse(theme=current_user.theme_preference)


@router.put("/theme", response_model=ThemePreferenceResponse)
async def update_theme_preference(
    request: ThemePreferenceRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update current user's theme preference.

    Args:
        request: Theme preference request ('light' or 'dark')
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated theme preference
    """
    try:
        # Update theme preference
        current_user.theme_preference = request.theme
        await db.commit()
        await db.refresh(current_user)

        logger.info(f"User {current_user.email} updated theme preference to {request.theme}")

        return ThemePreferenceResponse(theme=current_user.theme_preference)

    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating theme preference for user {current_user.email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update theme preference"
        )
