"""Parent/guardian pages for linked participants under 18.

Access is by relationship only (minor.guardian_user_id == current user). Being a
guardian grants no role or permission and changes nothing else in the account.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import bad_request, forbidden
from app.api.utils.request import extract_client_metadata
from app.dependencies import get_current_active_user, get_db, require_permission
from app.models.event import EventParticipation
from app.models.guardian_consent import GuardianLinkStatus
from app.models.user import User
from app.services import minor_service
from app.services.event_service import EventService

router = APIRouter(prefix="/api/guardian", tags=["Guardian"])

_LINKED = (GuardianLinkStatus.PENDING.value, GuardianLinkStatus.CONFIRMED.value)


async def require_guardian_of(
    minor_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """The minor, if (and only if) the caller is their linked parent/guardian."""
    minor = await db.get(User, minor_id)
    if (minor is None or minor.guardian_user_id != current_user.id
            or minor.guardian_link_status not in _LINKED):
        raise forbidden("Not linked to this participant")
    return minor


async def _status(db: AsyncSession, minor: User, guardian: User) -> dict:
    event = await EventService(db).get_current_event()
    participation = None
    consent = None
    guardian_confirmed = False
    if event is not None:
        participation = (await db.execute(
            select(EventParticipation).where(
                EventParticipation.user_id == minor.id, EventParticipation.event_id == event.id,
            )
        )).scalar_one_or_none()
        consent = await minor_service.active_consent(db, minor, event.id)
        guardian_confirmed = await minor_service.is_confirmed_for_event(db, guardian.id, event.id)
    minor_name = f"{minor.first_name} {minor.last_name}"
    return {
        "id": minor.id,
        "name": minor_name,
        "email": minor.email,
        "link_status": minor.guardian_link_status,
        "adult_on": minor.adult_on.isoformat() if minor.adult_on else None,
        "event": {"id": event.id, "name": event.name, "terms_version": event.terms_version,
                  "terms_content": event.terms_content} if event else None,
        "you_are_confirmed_for_event": guardian_confirmed,
        # Onboarding status: the same fields a referrer sees
        "onboarding": {
            "registered": participation is not None and participation.status == "confirmed",
            "activated": bool(participation and participation.activated_at),
            "suspended": bool(participation and participation.suspended_at),
            "event_service_username": minor.pandas_username,
            "discord_username": minor.discord_username,
            "email_status": minor.email_status,
            "in_person": bool(minor.confirmed_in_person),
        },
        "consent": {
            "given": consent is not None,
            "consented_at": consent.consented_at.isoformat() if consent and consent.consented_at else None,
            "relationship": consent.relationship_type if consent else None,
            "optional_email_consent": consent.optional_email_consent if consent else None,
        },
        "consent_text": minor_service.consent_text(minor_name, event.name) if event else None,
        "consent_text_version": minor_service.CONSENT_TEXT_VERSION,
    }


@router.get("/minors")
async def list_my_minors(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    minors = (await db.execute(
        select(User).where(
            User.guardian_user_id == current_user.id, User.guardian_link_status.in_(_LINKED),
        ).order_by(User.first_name)
    )).scalars().all()
    return {"minors": [await _status(db, m, current_user) for m in minors]}


@router.get("/minors/{minor_id}")
async def get_my_minor(
    minor: User = Depends(require_guardian_of),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await _status(db, minor, current_user)


class ConsentRequest(BaseModel):
    relationship: str = Field(..., description="parent or legal_guardian")
    accept_terms: bool
    confirm_consent: bool
    guardian_name_typed: str = Field(..., min_length=3, max_length=255)
    optional_email_consent: bool = False


@router.post("/minors/{minor_id}/consent")
async def give_consent(
    data: ConsentRequest,
    request: Request,
    minor: User = Depends(require_guardian_of),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not data.accept_terms or not data.confirm_consent:
        raise bad_request("Accept the event terms and the consent statement to continue.")
    event = await EventService(db).get_current_event()
    if event is None:
        raise bad_request("There's no active event.")
    ip_address, user_agent = extract_client_metadata(request)
    try:
        await minor_service.record_consent(
            db, minor=minor, guardian=current_user, event=event,
            relationship=data.relationship, guardian_name_typed=data.guardian_name_typed,
            optional_email_consent=data.optional_email_consent,
            ip_address=ip_address, user_agent=user_agent,
        )
    except minor_service.MinorRuleError as e:
        raise bad_request(str(e))
    return {"success": True, "message": "Thanks. Consent recorded."}


@router.post("/minors/{minor_id}/withdraw")
async def withdraw_consent(
    minor: User = Depends(require_guardian_of),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    event = await EventService(db).get_current_event()
    if event is None or not await minor_service.withdraw_consent(
        db, minor=minor, guardian=current_user, event=event
    ):
        raise bad_request("There's no consent to withdraw.")
    return {"success": True, "message": "Consent withdrawn. Their access is suspended."}


@router.post("/minors/{minor_id}/reject")
async def reject_link(
    minor: User = Depends(require_guardian_of),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """'I'm not this person's parent or guardian.'"""
    await minor_service.reject_link(db, minor=minor, guardian=current_user)
    return {"success": True}


class AdminLinkRequest(BaseModel):
    guardian_user_id: Optional[int] = None


admin_router = APIRouter(prefix="/api/admin", tags=["Admin - Minors"])


async def _minor_row(db: AsyncSession, minor: User, event) -> dict:
    guardian = await db.get(User, minor.guardian_user_id) if minor.guardian_user_id else None
    cleared = await minor_service.participant_is_cleared(db, minor, event) if event else None
    return {
        "id": minor.id,
        "name": f"{minor.first_name} {minor.last_name}",
        "email": minor.email,
        "adult_on": minor.adult_on.isoformat() if minor.adult_on else None,
        "guardian": ({"id": guardian.id, "name": f"{guardian.first_name} {guardian.last_name}",
                      "in_person": bool(guardian.confirmed_in_person)} if guardian else None),
        "guardian_link_status": minor.guardian_link_status,
        "guardian_email_pending": bool(minor.guardian_email_pending),
        "cleared_for_event": cleared,
        "in_person": bool(minor.confirmed_in_person),
    }


@admin_router.get("/minors")
async def admin_list_minors(
    current_user: User = Depends(require_permission("participants.view_all")),
    db: AsyncSession = Depends(get_db),
):
    """Participants under 18 (admins only; never shown to other participants)."""
    event = await EventService(db).get_current_event()
    users = (await db.execute(
        select(User).where(User.adult_on.isnot(None)).order_by(User.last_name)
    )).scalars().all()
    minors = [u for u in users if u.is_minor]
    return {"event": event.name if event else None,
            "minors": [await _minor_row(db, m, event) for m in minors]}


@admin_router.put("/participants/{participant_id}/guardian")
async def admin_set_guardian(
    participant_id: int,
    data: AdminLinkRequest,
    current_user: User = Depends(require_permission("participants.edit", "participants.view_all")),
    db: AsyncSession = Depends(get_db),
):
    """Link (or unlink, with null) a minor's guardian when the self-service link can't."""
    minor = await db.get(User, participant_id)
    if minor is None:
        raise bad_request("Participant not found")
    if data.guardian_user_id is None:
        minor.guardian_user_id = None
        minor.guardian_link_status = None
        await db.commit()
        await minor_service._audit(db, "GUARDIAN_LINK_CLEARED_BY_ADMIN", current_user.id, minor.id, None)
        event = await EventService(db).get_current_event()
        if event is not None:
            await minor_service.suspend_minor(db, minor, event, reason="guardian_unlinked")
        return {"guardian_user_id": None}
    guardian = await db.get(User, data.guardian_user_id)
    if guardian is None:
        raise bad_request("Guardian not found")
    try:
        await minor_service.admin_link(db, minor=minor, guardian=guardian, admin_id=current_user.id)
    except minor_service.MinorRuleError as e:
        raise bad_request(str(e))
    return {"guardian_user_id": guardian.id, "guardian_link_status": minor.guardian_link_status}
