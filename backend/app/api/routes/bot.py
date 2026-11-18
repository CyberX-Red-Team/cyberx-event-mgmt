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

from app.api.utils.validation import normalize_email
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


class AdminLinkRequest(BaseModel):
    email: str | None = None
    user_id: int | None = None
    discord_id: str
    discord_username: str | None = None


class AdminLinkResponse(BaseModel):
    linked: bool
    user_id: int
    user_email: str
    user_name: str
    message: str


class UserUpdateRequest(BaseModel):
    discord_username: str | None = None


class UserUpdateResponse(BaseModel):
    updated: bool
    user_id: int
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

    # One-time use: reject if this code has already been used
    if participation.discord_invite_used_at:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invite code has already been used",
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

    # Link the Discord identity and mark code as verified
    user.snowflake_id = body.discord_id
    if body.discord_username:
        user.discord_username = body.discord_username
    now = datetime.now(timezone.utc)
    participation.discord_invite_used_at = now
    participation.discord_verified_at = now
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


@router.patch("/user/{discord_id}", response_model=UserUpdateResponse)
async def update_user_by_discord(
    discord_id: str,
    body: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    api_key: ServiceAPIKey | None = Depends(require_service_api_key),
):
    """Update a platform user's Discord-related fields.

    Allows the bot to keep Discord usernames in sync when users change
    their display name on Discord.
    """
    _check_scope(api_key, "bot.update")

    result = await db.execute(
        select(User).where(User.snowflake_id == discord_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No linked user found for this Discord ID",
        )

    if body.discord_username is not None:
        user.discord_username = body.discord_username

    await db.commit()

    logger.info(
        "Discord user updated: user_id=%s discord_id=%s",
        user.id, discord_id,
    )

    return UserUpdateResponse(
        updated=True,
        user_id=user.id,
        message="User updated successfully",
    )


@router.post("/admin-link", response_model=AdminLinkResponse)
async def admin_link_discord(
    body: AdminLinkRequest,
    db: AsyncSession = Depends(get_db),
    api_key: ServiceAPIKey | None = Depends(require_service_api_key),
):
    """Admin override to link a Discord user to a platform user.

    Bypasses the invite code flow — looks up the user by email or user_id
    and directly sets their Discord identity.  Overwrites any existing link.
    """
    _check_scope(api_key, "bot.admin_link")

    if not body.email and not body.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'email' or 'user_id' is required",
        )

    # Look up user
    if body.user_id:
        result = await db.execute(
            select(User).where(User.id == body.user_id)
        )
    else:
        result = await db.execute(
            select(User).where(User.email_normalized == normalize_email(body.email))
        )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Link (overwrite any existing Discord link)
    user.snowflake_id = body.discord_id
    if body.discord_username is not None:
        user.discord_username = body.discord_username

    # Mark invite code as used on current event participation (if exists)
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
        if participation:
            now = datetime.now(timezone.utc)
            if not participation.discord_invite_used_at:
                participation.discord_invite_used_at = now
            participation.discord_verified_at = now

    await db.commit()

    logger.info(
        "Admin Discord link: user_id=%s discord_id=%s",
        user.id, body.discord_id,
    )

    return AdminLinkResponse(
        linked=True,
        user_id=user.id,
        user_email=user.email,
        user_name=f"{user.first_name} {user.last_name}".strip(),
        message="Discord account linked successfully (admin override)",
    )


# ─── Invite revocation (called by the external bot after archive) ────

class PendingInviteRevocation(BaseModel):
    event_id: int
    event_year: int
    participation_id: int
    invite_code: str
    generated_at: datetime | None


class InviteRevokedResponse(BaseModel):
    nulled: bool
    message: str


@router.get(
    "/invites/pending-revocation",
    response_model=list[PendingInviteRevocation],
)
async def list_pending_invite_revocations(
    db: AsyncSession = Depends(get_db),
    api_key: ServiceAPIKey | None = Depends(require_service_api_key),
):
    """Return invite codes on archived events that the bot should revoke.

    Criteria:
      - event.is_archived = True
      - EventParticipation.discord_invite_code IS NOT NULL
      - EventParticipation.discord_verified_at IS NULL (never used)

    The bot polls this, calls Discord's DELETE /invites/{code}, then POSTs
    back to /api/bot/invites/{code}/revoked so the platform can null the
    stored code.
    """
    _check_scope(api_key, "bot.manage_invites")

    result = await db.execute(
        select(EventParticipation, Event)
        .join(Event, Event.id == EventParticipation.event_id)
        .where(
            Event.is_archived == True,
            EventParticipation.discord_invite_code.is_not(None),
            EventParticipation.discord_verified_at.is_(None),
        )
        .order_by(Event.year.desc(), EventParticipation.id)
    )

    return [
        PendingInviteRevocation(
            event_id=event.id,
            event_year=event.year,
            participation_id=participation.id,
            invite_code=participation.discord_invite_code,
            generated_at=participation.discord_invite_generated_at,
        )
        for participation, event in result.all()
    ]


@router.post(
    "/invites/{invite_code}/revoked",
    response_model=InviteRevokedResponse,
)
async def mark_invite_revoked(
    invite_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: ServiceAPIKey | None = Depends(require_service_api_key),
):
    """Bot callback: Discord invite was successfully revoked (or confirmed 404)."""
    _check_scope(api_key, "bot.manage_invites")

    result = await db.execute(
        select(EventParticipation).where(
            EventParticipation.discord_invite_code == invite_code
        )
    )
    participation = result.scalar_one_or_none()

    if not participation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No participation found with that invite code",
        )

    event_id = participation.event_id
    participation.discord_invite_code = None
    await db.commit()

    from app.services.audit_service import AuditService
    audit = AuditService(db)
    ip = request.client.host if request.client else None
    actor_name = api_key.name if api_key else "env-fallback"
    await audit.log_discord_invite_revoked(
        actor_id=None,
        invite_code=invite_code,
        event_id=event_id,
        ip_address=ip,
        user_agent=f"bot:{actor_name}",
    )

    return InviteRevokedResponse(
        nulled=True,
        message=f"Invite code {invite_code} marked revoked; DB reference cleared.",
    )


# ─── Verified-role reconciliation roster ─────────────────────────────

class VerifiedRosterResponse(BaseModel):
    active_event: dict | None  # {id, year, name} or null between seasons
    verified_discord_ids: list[str]
    count: int


@router.get("/verified-roster", response_model=VerifiedRosterResponse)
async def verified_roster(
    db: AsyncSession = Depends(get_db),
    api_key: ServiceAPIKey | None = Depends(require_service_api_key),
):
    """Snowflake IDs that SHOULD currently hold the verified Discord role.

    Definition: users linked to Discord (snowflake_id set) who have verified
    (discord_verified_at) for the currently ACTIVE event. The bot reconciles
    the role against this set — removing it from anyone holding it who isn't
    listed, optionally adding it to listed members who lack it.

    When there is NO active event (e.g. between seasons after an archive),
    active_event is null and the list is empty — the bot treats that as a
    legitimate signal to clear the role for everyone. A failed call (non-200)
    must NOT be treated that way; the bot skips reconciliation on error so a
    transient outage can't strip every verified member.
    """
    _check_scope(api_key, "bot.manage_roles")

    active_event = (
        await db.execute(
            select(Event)
            .where(Event.is_active == True)  # noqa: E712
            .order_by(Event.year.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if active_event is None:
        return VerifiedRosterResponse(
            active_event=None, verified_discord_ids=[], count=0
        )

    rows = (
        await db.execute(
            select(User.snowflake_id)
            .join(EventParticipation, EventParticipation.user_id == User.id)
            .where(
                EventParticipation.event_id == active_event.id,
                EventParticipation.discord_verified_at.is_not(None),
                User.snowflake_id.is_not(None),
            )
        )
    ).scalars().all()

    ids = [s for s in rows if s]
    return VerifiedRosterResponse(
        active_event={
            "id": active_event.id,
            "year": active_event.year,
            "name": active_event.name,
        },
        verified_discord_ids=ids,
        count=len(ids),
    )
