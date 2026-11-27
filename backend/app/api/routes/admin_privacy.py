"""Admin privacy tools: retention status/dry run, data-deletion requests,
retention holds, and the do-not-invite list.

Audit entries written here hold IDs and counts only, never personal data.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import bad_request, forbidden, not_found
from app.api.utils.request import extract_client_metadata
from app.config import get_settings
from app.dependencies import get_db, require_permission
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.invite_suppression_service import InviteSuppressionService
from app.services.participant_service import ParticipantService
from app.services.retention_service import RUN_ACTION, RetentionService

router = APIRouter(prefix="/api/admin", tags=["Admin - Privacy"])

# Retention settings and dry runs reveal counts only, but deletion and the
# do-not-invite list act on anyone: admin-level permissions throughout.
_SETTINGS_PERMS = ("admin.manage_settings",)
_DELETE_PERMS = ("participants.remove", "participants.view_all")
_EDIT_PERMS = ("participants.edit", "participants.view_all")


def _retention_settings() -> dict:
    s = get_settings()
    return {
        "enabled": s.RETENTION_ENABLED,
        "invitee_months": s.RETENTION_INVITEE_MONTHS,
        "inactive_account_months": s.RETENTION_INACTIVE_ACCOUNT_MONTHS,
        "inactive_warning_days": s.RETENTION_INACTIVE_WARNING_DAYS,
        "log_days": s.RETENTION_LOG_DAYS,
        "event_closeout_days": s.RETENTION_EVENT_CLOSEOUT_DAYS,
        "legacy_future_invites_enabled": s.LEGACY_FUTURE_INVITES_ENABLED,
    }


@router.get("/retention/status")
async def retention_status(
    current_user: User = Depends(require_permission("participants.view_all")),
    db: AsyncSession = Depends(get_db),
):
    """Retention settings, the latest run's counts, and events overdue for close-out."""
    last = (await db.execute(
        select(AuditLog).where(AuditLog.action == RUN_ACTION)
        .order_by(AuditLog.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    overdue = await RetentionService(db).overdue_events()
    today = datetime.now(timezone.utc).date()
    return {
        "settings": _retention_settings(),
        "last_run": (
            {"at": last.created_at.isoformat() if last.created_at else None, "results": last.details}
            if last else None
        ),
        "overdue_events": [
            {"id": e.id, "name": e.name, "end_date": e.end_date.isoformat(),
             "days_since_end": (today - e.end_date).days}
            for e in overdue
        ],
    }


@router.post("/retention/dry-run")
async def retention_dry_run(
    request: Request,
    current_user: User = Depends(require_permission(*_SETTINGS_PERMS)),
    db: AsyncSession = Depends(get_db),
):
    """What the retention job would do right now. Changes nothing."""
    results = await RetentionService(db).run_all(dry_run=True)
    ip_address, user_agent = extract_client_metadata(request)
    await AuditService(db).log(
        action=RUN_ACTION,
        user_id=current_user.id,
        resource_type="SYSTEM",
        details={**results, "trigger": "manual"},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return results


class DataDeletionRequest(BaseModel):
    confirm_email: str = Field(..., min_length=3, max_length=255)


@router.post("/participants/{participant_id}/delete-data")
async def delete_participant_data(
    participant_id: int,
    data: DataDeletionRequest,
    request: Request,
    current_user: User = Depends(require_permission(*_DELETE_PERMS)),
    db: AsyncSession = Depends(get_db),
):
    """
    Act on a data-deletion request (e.g. received at the privacy contact
    address): delete the account and scrub every copy of the person's identity
    right away. Typed confirmation: the person's email on file.
    """
    service = ParticipantService(db)
    participant = await service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant")
    if participant.id == current_user.id:
        raise forbidden("You can't delete your own account here")
    if data.confirm_email.strip().lower() != (participant.email or "").strip().lower():
        raise bad_request("Type the person's email address exactly as shown to confirm")

    if not await service.delete_participant(participant_id):
        raise not_found("Participant")

    ip_address, user_agent = extract_client_metadata(request)
    await AuditService(db).log(
        action="DATA_DELETION_REQUEST",
        user_id=current_user.id,
        resource_type="USER",
        resource_id=participant_id,
        details={"target_user_id": participant_id},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return {"message": "Participant data deleted"}


class RetentionHoldRequest(BaseModel):
    until: Optional[datetime] = Field(None, description="Keep until this time; null clears the hold")


@router.put("/participants/{participant_id}/retention-hold")
async def set_retention_hold(
    participant_id: int,
    data: RetentionHoldRequest,
    request: Request,
    current_user: User = Depends(require_permission(*_EDIT_PERMS)),
    db: AsyncSession = Depends(get_db),
):
    """Keep an account past the inactivity rule (e.g. the person replied to the notice)."""
    user = await db.get(User, participant_id)
    if not user:
        raise not_found("Participant")
    until = data.until
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    user.retention_hold_until = until
    if until is not None:
        user.deletion_warning_sent_at = None  # a hold cancels a pending notice
    await db.commit()

    ip_address, user_agent = extract_client_metadata(request)
    await AuditService(db).log(
        action="RETENTION_HOLD_SET",
        user_id=current_user.id,
        resource_type="USER",
        resource_id=participant_id,
        details={"until": until.isoformat() if until else None},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return {"retention_hold_until": until.isoformat() if until else None}


class SuppressionRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


@router.post("/invite-suppressions/check")
async def check_suppression(
    data: SuppressionRequest,
    current_user: User = Depends(require_permission(*_EDIT_PERMS)),
    db: AsyncSession = Depends(get_db),
):
    return {"suppressed": await InviteSuppressionService(db).is_suppressed(data.email)}


@router.post("/invite-suppressions")
async def add_suppression(
    data: SuppressionRequest,
    request: Request,
    current_user: User = Depends(require_permission(*_EDIT_PERMS)),
    db: AsyncSession = Depends(get_db),
):
    """Add someone who asked (e.g. by email) not to be invited again."""
    added = await InviteSuppressionService(db).add(data.email)
    await db.commit()
    ip_address, user_agent = extract_client_metadata(request)
    await AuditService(db).log(
        action="INVITE_SUPPRESSION_ADDED",
        user_id=current_user.id,
        details={"already_present": not added},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return {"suppressed": True, "added": added}


@router.post("/invite-suppressions/remove")
async def remove_suppression(
    data: SuppressionRequest,
    request: Request,
    current_user: User = Depends(require_permission(*_EDIT_PERMS)),
    db: AsyncSession = Depends(get_db),
):
    """Remove an entry when the person asks to be invited again."""
    removed = await InviteSuppressionService(db).remove(data.email)
    await db.commit()
    ip_address, user_agent = extract_client_metadata(request)
    await AuditService(db).log(
        action="INVITE_SUPPRESSION_REMOVED",
        user_id=current_user.id,
        details={"was_present": removed},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return {"suppressed": False, "removed": removed}
