"""User preference routes."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.dependencies import get_current_active_user

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
        # Merge user into this session (may have been loaded in a different session)
        user = await db.merge(current_user)
        user.theme_preference = request.theme
        await db.commit()

        logger.info(f"User {current_user.email} updated theme preference to {request.theme}")

        return ThemePreferenceResponse(theme=user.theme_preference)

    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating theme preference for user {current_user.email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update theme preference"
        )


class PrivacyPreferences(BaseModel):
    """The signed-in user's privacy choices."""
    future_contact_consent: bool = Field(
        ..., description="Invite me to future CyberX events and send me announcements"
    )


@router.get("/privacy")
async def get_privacy_preferences(
    current_user: User = Depends(get_current_active_user),
):
    return {
        "future_contact_consent": current_user.future_contact_consent,
        "future_contact_consent_at": (
            current_user.future_contact_consent_at.isoformat()
            if current_user.future_contact_consent_at else None
        ),
    }


@router.put("/privacy")
async def update_privacy_preferences(
    data: PrivacyPreferences,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Give or withdraw consent to future invitations and announcements."""
    from app.services.audit_service import AuditService
    from app.services.consent_service import set_future_contact_consent
    from app.api.utils.request import extract_client_metadata

    user = await db.get(User, current_user.id)
    set_future_contact_consent(user, data.future_contact_consent)
    await db.commit()
    ip_address, user_agent = extract_client_metadata(request)
    await AuditService(db).log(
        user_id=user.id,
        action="PRIVACY_CHOICES_RECORDED",
        resource_type="USER",
        resource_id=user.id,
        details={"source": "profile", "future_contact_consent": data.future_contact_consent},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return {"future_contact_consent": user.future_contact_consent}


@router.post("/export")
async def download_my_data(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """'Download my data' on the profile page: a ZIP of everything we hold about
    the signed-in person. One per DATA_EXPORT_SELF_SERVICE_HOURS."""
    from app.api.utils.request import extract_client_metadata
    from app.config import get_settings
    from app.services.audit_service import AuditService
    from app.services.data_export_service import DataExportService, recent_export_exists, zip_response

    hours = get_settings().DATA_EXPORT_SELF_SERVICE_HOURS
    if await recent_export_exists(db, current_user.id, hours):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You can download your data once every {hours} hours. Please try again later.",
        )
    filename, blob = await DataExportService(db).export_user(current_user.id)
    ip_address, user_agent = extract_client_metadata(request)
    await AuditService(db).log(
        action="DATA_EXPORT_CREATED", user_id=current_user.id, resource_type="USER",
        resource_id=current_user.id, details={"target_user_id": current_user.id, "delivery": "self_service"},
        ip_address=ip_address, user_agent=user_agent,
    )
    return zip_response(filename, blob)
