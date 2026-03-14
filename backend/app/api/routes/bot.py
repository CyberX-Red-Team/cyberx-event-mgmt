"""Bot API routes — external Discord bot integration."""
import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.dependencies import get_db
from app.models.event import Event, EventParticipation
from app.models.role import Role
from app.models.service_api_key import ServiceAPIKey
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/bot", tags=["Bot"])


# ─── Auth dependency ──────────────────────────────────────────────────

async def require_service_api_key(
    request: Request,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> ServiceAPIKey | None:
    """Authenticate via DB-stored service API key, with env var fallback.

    Checks the Bearer token against service_api_keys table first.
    Falls back to BOT_API_KEY env var for backwards compatibility.
    Returns the ServiceAPIKey row (or None for env var auth).
    """
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
        )
    raw_token = parts[1]

    # Try DB-stored key first
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    result = await db.execute(
        select(ServiceAPIKey).where(
            ServiceAPIKey.key_hash == token_hash,
            ServiceAPIKey.is_active == True,
        )
    )
    api_key = result.scalar_one_or_none()

    if api_key:
        # Check expiry
        if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired",
            )
        # Update usage tracking
        api_key.last_used_at = datetime.now(timezone.utc)
        api_key.last_used_ip = request.client.host if request.client else None
        await db.commit()
        return api_key

    # Fallback to env var
    if settings.BOT_API_KEY and hmac.compare_digest(raw_token, settings.BOT_API_KEY):
        return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
    )


def _check_scope(api_key: ServiceAPIKey | None, scope: str) -> None:
    """Verify the API key has the required scope (env var keys have all scopes)."""
    if api_key is None:
        return  # env var fallback — full access
    if scope not in (api_key.scopes or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key does not have '{scope}' scope",
        )


# ─── Schemas ──────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    invite_code: str
    discord_id: str
    discord_username: str | None = None


class VerifyResponse(BaseModel):
    linked: bool
    user_email: str
    user_name: str
    message: str


class UserRoleInfo(BaseModel):
    base_type: str  # admin/sponsor/invitee
    role_name: str | None = None  # dynamic role name (e.g., "Event Staff")
    role_slug: str | None = None  # dynamic role slug


class EventParticipationInfo(BaseModel):
    event_name: str
    event_year: int
    status: str | None  # confirmed/declined/invited/no_response


class UserLookupResponse(BaseModel):
    user_id: int
    email: str
    first_name: str
    last_name: str
    discord_id: str | None
    discord_username: str | None
    role: UserRoleInfo
    participation: EventParticipationInfo | None


# ─── Routes ───────────────────────────────────────────────────────────

@router.post("/verify", response_model=VerifyResponse)
async def verify_discord_user(
    body: VerifyRequest,
    db: AsyncSession = Depends(get_db),
    api_key: ServiceAPIKey | None = Depends(require_service_api_key),
):
    """Link a Discord user to a platform user via their invite code.

    The bot sends the invite code (from /verify slash command) along with
    the Discord user's snowflake ID.  We look up the participation record
    by invite code, then set the snowflake_id on the associated user.
    """
    _check_scope(api_key, "bot.verify")

    # Find participation by invite code
    result = await db.execute(
        select(EventParticipation).where(
            EventParticipation.discord_invite_code == body.invite_code
        )
    )
    participation = result.scalar_one_or_none()

    if not participation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite code",
        )

    # Load the user
    user_result = await db.execute(
        select(User).where(User.id == participation.user_id)
    )
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Check if already linked to a different Discord user
    if user.snowflake_id and user.snowflake_id != body.discord_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account is already linked to a different Discord user",
        )

    # Link the Discord identity
    user.snowflake_id = body.discord_id
    if body.discord_username:
        user.discord_username = body.discord_username
    await db.commit()

    logger.info(
        "Discord linked: user_id=%s discord_id=%s",
        user.id, body.discord_id,
    )

    return VerifyResponse(
        linked=True,
        user_email=user.email,
        user_name=f"{user.first_name} {user.last_name}".strip(),
        message="Discord account linked successfully",
    )


@router.get("/user/{discord_id}", response_model=UserLookupResponse)
async def lookup_user_by_discord(
    discord_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: ServiceAPIKey | None = Depends(require_service_api_key),
):
    """Look up a platform user by their Discord snowflake ID.

    Returns user info, their dynamic role, and current event participation
    status.  Useful for the bot to auto-assign Discord roles based on
    platform state.
    """
    _check_scope(api_key, "bot.lookup")

    # Find user by snowflake_id, eager-load role
    result = await db.execute(
        select(User)
        .options(selectinload(User.role_obj))
        .where(User.snowflake_id == discord_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No linked user found for this Discord ID",
        )

    # Build role info
    role_info = UserRoleInfo(
        base_type=user.role or "invitee",
        role_name=user.role_obj.name if user.role_obj else None,
        role_slug=user.role_obj.slug if user.role_obj else None,
    )

    # Get current event participation
    participation_info = None
    event_result = await db.execute(
        select(Event)
        .where(Event.is_active == True)
        .order_by(Event.year.desc())
        .limit(1)
    )
    active_event = event_result.scalar_one_or_none()

    if active_event:
        part_result = await db.execute(
            select(EventParticipation).where(
                EventParticipation.user_id == user.id,
                EventParticipation.event_id == active_event.id,
            )
        )
        participation = part_result.scalar_one_or_none()

        participation_info = EventParticipationInfo(
            event_name=active_event.name,
            event_year=active_event.year,
            status=participation.status if participation else None,
        )

    return UserLookupResponse(
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        discord_id=user.snowflake_id,
        discord_username=user.discord_username,
        role=role_info,
        participation=participation_info,
    )
