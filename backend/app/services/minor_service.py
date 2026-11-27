"""
Participants aged 16 or 17.

Rules (Privacy Policy "Age" section and the organizers' rules):
- Minimum age 16. 16- and 17-year-olds take part only with written consent from
  a parent or guardian who is also a confirmed participant in the same event.
- The guardian link is a relationship between two accounts, never a role or
  permission. Guardian access is checked by relationship only.
- A minor's event access is activated only once valid consent is recorded, and
  suspended when it stops being valid.
- In person only if the guardian also attends in person.
- At 18 the minor rules stop applying from the next event on.

Audit entries written here hold IDs only.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils.validation import normalize_email
from app.models.event import Event, EventParticipation, ParticipationStatus
from app.models.guardian_consent import GuardianConsent, GuardianLinkStatus, GuardianRelationship
from app.models.user import User

logger = logging.getLogger(__name__)

MINIMUM_AGE = 16
ADULT_AGE = 18
PENDING_GUARDIAN_EMAIL_DAYS = 30

AGE_ATTESTATION_ADULT = "adult_v2"
AGE_ATTESTATION_MINOR = "minor_with_guardian_v2"

# Draft wording (v1), pending organizer confirmation. Changing it means a new version.
CONSENT_TEXT_VERSION = "guardian-consent-v1"
CONSENT_TEXT_V1 = (
    "I am the parent or legal guardian of {minor}. I consent to {minor} taking part in "
    "{event} as a red team operator, accept the event terms on their behalf, and confirm "
    "I am also taking part in this event. I understand {minor} may attend in person only "
    "if I also attend in person. I can withdraw this consent at any time."
)

UNDER_16_MESSAGE = "You need to be at least 16 to take part."
IN_PERSON_MESSAGE = (
    "You can attend in person only if your parent or guardian also attends in person."
)


class MinorRuleError(Exception):
    """A request that the minor rules don't allow (message is safe to show)."""


# ------------------------------------------------------------------ ages

def first_of_month(year: int, month: int) -> date:
    if not (1 <= month <= 12) or not (1900 <= year <= date.today().year):
        raise MinorRuleError("Enter a valid birth month and year.")
    return date(year, month, 1)


def turns(birth_year_month: date, years: int) -> date:
    """First day of the month the person reaches `years` (no day of birth is stored)."""
    return date(birth_year_month.year + years, birth_year_month.month, 1)


def age_bracket(birth_year_month: date, on: date) -> str:
    """'under_16', 'minor' (16-17) or 'adult' on the given date."""
    if on < turns(birth_year_month, MINIMUM_AGE):
        return "under_16"
    if on < turns(birth_year_month, ADULT_AGE):
        return "minor"
    return "adult"


def _event_reference_date(event: Optional[Event]) -> date:
    if event is not None and event.start_date is not None:
        start = event.start_date
        return start.date() if isinstance(start, datetime) else start
    return date.today()


def is_minor_for_event(user: User, event: Optional[Event]) -> bool:
    """Minor rules apply to this event (turning 18 mid-event doesn't change that)."""
    if user.adult_on is None:
        return False
    return user.adult_on > _event_reference_date(event)


def consent_text(minor_name: str, event_name: str) -> str:
    return CONSENT_TEXT_V1.format(minor=minor_name, event=event_name)


# --------------------------------------------------------------- lookups

async def _participation(db: AsyncSession, user_id: int, event_id: int) -> Optional[EventParticipation]:
    return (await db.execute(
        select(EventParticipation).where(
            EventParticipation.user_id == user_id, EventParticipation.event_id == event_id,
        )
    )).scalar_one_or_none()


async def is_confirmed_for_event(db: AsyncSession, user_id: Optional[int], event_id: int) -> bool:
    if user_id is None:
        return False
    p = await _participation(db, user_id, event_id)
    return p is not None and p.status == ParticipationStatus.CONFIRMED.value


async def active_consent(db: AsyncSession, minor: User, event_id: int) -> Optional[GuardianConsent]:
    return (await db.execute(
        select(GuardianConsent).where(
            GuardianConsent.minor_user_id == minor.id,
            GuardianConsent.event_id == event_id,
            GuardianConsent.withdrawn_at.is_(None),
        ).order_by(GuardianConsent.consented_at.desc())
    )).scalars().first()


async def latest_consent(db: AsyncSession, minor_id: int) -> Optional[GuardianConsent]:
    return (await db.execute(
        select(GuardianConsent).where(GuardianConsent.minor_user_id == minor_id)
        .order_by(GuardianConsent.consented_at.desc(), GuardianConsent.id.desc())
    )).scalars().first()


async def has_valid_consent(db: AsyncSession, minor: User, event: Event) -> bool:
    """Consent row for (minor, event) not withdrawn, from the linked guardian, who is
    a confirmed participant in that event."""
    consent = await active_consent(db, minor, event.id)
    if consent is None or consent.guardian_user_id is None:
        return False
    if minor.guardian_user_id != consent.guardian_user_id:
        return False
    if minor.guardian_link_status != GuardianLinkStatus.CONFIRMED.value:
        return False
    return await is_confirmed_for_event(db, consent.guardian_user_id, event.id)


async def participant_is_cleared(db: AsyncSession, user: User, event: Optional[Event]) -> bool:
    """May this person use event access (VPN, instances, TLS, CPE) for `event`?"""
    if event is None or not is_minor_for_event(user, event):
        return True
    participation = await _participation(db, user.id, event.id)
    if participation is None or participation.activated_at is None or participation.suspended_at:
        return False
    return await has_valid_consent(db, user, event)


async def optional_email_allowed(db: AsyncSession, user: User) -> bool:
    """Announcements / future invitations to a minor need the guardian's consent too."""
    from app.services.consent_service import may_receive_optional_email
    if not may_receive_optional_email(user):
        return False
    if not user.is_minor:
        return True
    consent = await latest_consent(db, user.id)
    return bool(consent and consent.withdrawn_at is None and consent.optional_email_consent)


# --------------------------------------------------------------- linking

async def link_guardian_by_email(db: AsyncSession, minor: User, event: Event, email: str) -> bool:
    """
    Minor names their guardian. If the email matches a confirmed participant in
    the same event, store a pending link and ask the guardian for consent.
    Otherwise keep the typed email (for up to 30 days) and tell the admins.
    Returns True when linked. Doesn't commit.
    """
    normalized = normalize_email(email)
    if not normalized or normalized == minor.email_normalized:
        raise MinorRuleError("Enter your parent or guardian's email address.")
    guardian = (await db.execute(
        select(User).where(User.email_normalized == normalized)
    )).scalar_one_or_none()

    if guardian is not None and await is_confirmed_for_event(db, guardian.id, event.id):
        _set_pending_link(minor, guardian.id)
        return True

    minor.guardian_user_id = None
    minor.guardian_link_status = None
    minor.guardian_email_pending = email.strip()
    minor.guardian_email_pending_at = datetime.now(timezone.utc)
    return False


def _set_pending_link(minor: User, guardian_id: int) -> None:
    minor.guardian_user_id = guardian_id
    minor.guardian_link_status = GuardianLinkStatus.PENDING.value
    minor.guardian_email_pending = None
    minor.guardian_email_pending_at = None


async def link_waiting_minors(db: AsyncSession, guardian: User, event: Event) -> list[int]:
    """A guardian just confirmed for `event`: link minors who typed their email."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=PENDING_GUARDIAN_EMAIL_DAYS)
    candidates = (await db.execute(
        select(User).where(User.guardian_email_pending.isnot(None))
    )).scalars().all()
    linked = []
    for minor in candidates:
        typed_at = minor.guardian_email_pending_at
        if typed_at is not None and typed_at.tzinfo is None:
            typed_at = typed_at.replace(tzinfo=timezone.utc)
        if typed_at is not None and typed_at < cutoff:
            continue
        if normalize_email(minor.guardian_email_pending) != guardian.email_normalized:
            continue
        if await _participation(db, minor.id, event.id) is None:
            continue
        _set_pending_link(minor, guardian.id)
        linked.append(minor.id)
    return linked


async def discard_stale_guardian_emails(db: AsyncSession, now: datetime, dry_run: bool) -> int:
    cutoff = now - timedelta(days=PENDING_GUARDIAN_EMAIL_DAYS)
    rows = (await db.execute(
        select(User.id).where(
            User.guardian_email_pending.isnot(None), User.guardian_email_pending_at < cutoff,
        )
    )).scalars().all()
    if rows and not dry_run:
        await db.execute(
            update(User).where(User.id.in_(rows))
            .values(guardian_email_pending=None, guardian_email_pending_at=None)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    return len(rows)


async def clear_birth_month_for_adults(db: AsyncSession, today: date, dry_run: bool) -> int:
    """Turning 18: birth month/year is no longer needed (adult_on and consents stay)."""
    rows = (await db.execute(
        select(User.id).where(User.birth_year_month.isnot(None), User.adult_on <= today)
    )).scalars().all()
    if rows and not dry_run:
        await db.execute(
            update(User).where(User.id.in_(rows)).values(birth_year_month=None)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    return len(rows)


# ------------------------------------------------------------- consent

async def record_consent(
    db: AsyncSession, *, minor: User, guardian: User, event: Event, relationship: str,
    guardian_name_typed: str, optional_email_consent: bool, ip_address: Optional[str],
    user_agent: Optional[str],
) -> GuardianConsent:
    """Guardian gives consent for one event, then the minor is activated (or resumed)."""
    if minor.guardian_user_id != guardian.id:
        raise MinorRuleError("You're not linked to this participant.")
    try:
        relationship = GuardianRelationship(relationship).value
    except ValueError:
        raise MinorRuleError("Choose your relationship to the participant.")
    if not guardian_name_typed or len(guardian_name_typed.strip()) < 3:
        raise MinorRuleError("Type your full name to sign.")
    if not await is_confirmed_for_event(db, guardian.id, event.id):
        raise MinorRuleError(
            "You need to be a confirmed participant in this event before you can give consent."
        )
    participation = await _participation(db, minor.id, event.id)
    if participation is None or participation.status != ParticipationStatus.CONFIRMED.value:
        raise MinorRuleError("This participant hasn't registered for this event yet.")

    now = datetime.now(timezone.utc)
    # One active consent per minor per event: a new one replaces the old.
    await db.execute(
        update(GuardianConsent).where(
            GuardianConsent.minor_user_id == minor.id, GuardianConsent.event_id == event.id,
            GuardianConsent.withdrawn_at.is_(None),
        ).values(withdrawn_at=now).execution_options(synchronize_session=False)
    )
    consent = GuardianConsent(
        minor_user_id=minor.id, guardian_user_id=guardian.id, event_id=event.id,
        relationship_type=relationship, guardian_name_typed=guardian_name_typed.strip(),
        consent_text_version=CONSENT_TEXT_VERSION, terms_version=event.terms_version,
        optional_email_consent=bool(optional_email_consent), consented_at=now,
        ip_address=ip_address, user_agent=user_agent,
    )
    db.add(consent)
    minor.guardian_link_status = GuardianLinkStatus.CONFIRMED.value
    await db.commit()

    await _audit(db, "GUARDIAN_CONSENT_GIVEN", guardian.id, minor.id, event.id)
    if participation.activated_at is None:
        from app.services.participant_service import ParticipantService
        await ParticipantService(db).activate_participation(minor, event, participation, now)
    elif participation.suspended_at is not None:
        await _resume(db, minor, participation)
    return consent


async def withdraw_consent(db: AsyncSession, *, minor: User, guardian: User, event: Event) -> bool:
    consent = await active_consent(db, minor, event.id)
    if consent is None or consent.guardian_user_id != guardian.id:
        return False
    consent.withdrawn_at = datetime.now(timezone.utc)
    await db.commit()
    await _audit(db, "GUARDIAN_CONSENT_WITHDRAWN", guardian.id, minor.id, event.id)
    await suspend_minor(db, minor, event, reason="consent_withdrawn")
    return True


async def reject_link(db: AsyncSession, *, minor: User, guardian: User) -> None:
    """'I'm not this person's parent or guardian.'"""
    minor.guardian_user_id = None
    minor.guardian_link_status = None
    await db.commit()
    await _audit(db, "GUARDIAN_LINK_REJECTED", guardian.id, minor.id, None)
    await notify_admins(db, "guardian_link_rejected", minor)
    event = await _current_event(db)
    if event is not None:
        await suspend_minor(db, minor, event, reason="guardian_link_rejected")


async def admin_link(db: AsyncSession, *, minor: User, guardian: User, admin_id: int) -> None:
    if guardian.id == minor.id:
        raise MinorRuleError("A participant can't be their own guardian.")
    _set_pending_link(minor, guardian.id)
    await db.commit()
    await _audit(db, "GUARDIAN_LINK_SET_BY_ADMIN", admin_id, minor.id, None,
                 extra={"guardian_user_id": guardian.id})
    event = await _current_event(db)
    if event is not None:
        await notify_guardian_consent_needed(db, minor, guardian, event)


# ----------------------------------------------------- suspend / resume

async def suspend_minor(db: AsyncSession, minor: User, event: Event, reason: str) -> bool:
    """Consent no longer valid: block access, disable event-service sign-in, cancel
    in-person attendance, revoke an unused Discord invite, tell everyone."""
    participation = await _participation(db, minor.id, event.id)
    if participation is None or participation.activated_at is None or participation.suspended_at:
        return False
    participation.suspended_at = datetime.now(timezone.utc)
    # Unused Discord invite: listed for the bot to revoke via pending-revocation.
    if minor.pandas_username:
        from app.models.password_sync_queue import PasswordSyncQueue, SyncOperation
        db.add(PasswordSyncQueue(
            user_id=minor.id, username=minor.pandas_username,
            operation=SyncOperation.DISABLE_USER.value,
        ))
    await cancel_in_person(db, minor, event)
    from app.services.session_revocation import revoke_user_sessions
    await revoke_user_sessions(db, [minor.id])
    await db.commit()
    await _audit(db, "MINOR_ACCESS_SUSPENDED", None, minor.id, event.id, extra={"reason": reason})
    await _send_transactional(db, minor, "minor_access_suspended", {"event_name": event.name})
    await notify_admins(db, "minor_access_suspended", minor)
    return True


async def _resume(db: AsyncSession, minor: User, participation: EventParticipation) -> None:
    participation.suspended_at = None
    if minor.pandas_username:
        from app.models.password_sync_queue import PasswordSyncQueue, SyncOperation
        db.add(PasswordSyncQueue(
            user_id=minor.id, username=minor.pandas_username,
            operation=SyncOperation.ENABLE_USER.value,
        ))
    await db.commit()
    await _audit(db, "MINOR_ACCESS_RESUMED", None, minor.id, participation.event_id)


async def guardian_participation_changed(db: AsyncSession, guardian: User, event: Event,
                                         reason: str) -> int:
    """Guardian declined, was removed, or their participation was cancelled."""
    minors = (await db.execute(
        select(User).where(User.guardian_user_id == guardian.id)
    )).scalars().all()
    count = 0
    for minor in minors:
        if is_minor_for_event(minor, event) and await suspend_minor(db, minor, event, reason):
            count += 1
    return count


# ------------------------------------------------------------ in person

async def guardian_attends_in_person(db: AsyncSession, minor: User) -> bool:
    if minor.guardian_user_id is None:
        return False
    guardian = await db.get(User, minor.guardian_user_id)
    return bool(guardian and guardian.confirmed_in_person)


async def cancel_in_person(db: AsyncSession, minor: User, event: Event) -> None:
    """Drop the minor's in-person attendance and cancel their in-person action(s)."""
    from app.models.participant_action import ActionStatus, ActionType, ParticipantAction
    minor.confirmed_in_person = False
    await db.execute(
        update(ParticipantAction).where(
            ParticipantAction.user_id == minor.id,
            ParticipantAction.event_id == event.id,
            ParticipantAction.action_type == ActionType.IN_PERSON_ATTENDANCE.value,
            ParticipantAction.status.in_((ActionStatus.PENDING.value, ActionStatus.CONFIRMED.value)),
        ).values(status=ActionStatus.CANCELLED.value).execution_options(synchronize_session=False)
    )


async def guardian_left_in_person(db: AsyncSession, guardian: User, event: Event) -> int:
    """Guardian no longer attends in person: their minors can't either."""
    minors = (await db.execute(
        select(User).where(User.guardian_user_id == guardian.id, User.confirmed_in_person.is_(True))
    )).scalars().all()
    for minor in minors:
        await cancel_in_person(db, minor, event)
    if minors:
        await db.commit()
        for minor in minors:
            await _send_transactional(db, minor, "minor_in_person_cancelled",
                                      {"event_name": event.name})
    return len(minors)


# ---------------------------------------------------------- messaging

async def _current_event(db: AsyncSession) -> Optional[Event]:
    from app.services.event_service import EventService
    return await EventService(db).get_current_event()


async def _audit(db, action, actor_id, minor_id, event_id, extra=None) -> None:
    from app.services.audit_service import AuditService
    details = {"minor_user_id": minor_id, "event_id": event_id, **(extra or {})}
    await AuditService(db).log(
        action=action, user_id=actor_id, resource_type="USER", resource_id=minor_id,
        details=details,
    )


async def _send_transactional(db, user: User, template: str, vars: dict) -> None:
    """Essential email to the minor; the queue copies it to their guardian."""
    from app.services.email_queue_service import EmailQueueService
    try:
        await EmailQueueService(db).enqueue_email(
            user_id=user.id, template_name=template, priority=3, force=True,
            custom_vars={"first_name": user.first_name, **vars},
        )
    except Exception:
        logger.exception("Could not queue %s for user %s", template, user.id)


async def notify_guardian_consent_needed(db, minor: User, guardian: User, event: Event) -> None:
    from app.config import get_settings
    from app.services.email_queue_service import EmailQueueService
    try:
        await EmailQueueService(db).enqueue_email(
            user_id=guardian.id, template_name="guardian_consent_needed", priority=3, force=True,
            custom_vars={
                "first_name": guardian.first_name,
                "minor_name": f"{minor.first_name} {minor.last_name}",
                "event_name": event.name,
                "portal_url": f"{get_settings().FRONTEND_URL}/portal/minors",
            },
        )
    except Exception:
        logger.exception("Could not queue consent request for guardian %s", guardian.id)


async def notify_admins(db, reason: str, minor: User) -> None:
    """Tell admins something needs a look (IDs and a link only)."""
    from app.config import get_settings
    from app.services.email_queue_service import EmailQueueService
    admins = (await db.execute(
        select(User.id, User.first_name).where(User.role == "admin", User.is_active.is_(True))
    )).all()
    queue = EmailQueueService(db)
    for admin_id, first_name in admins:
        try:
            await queue.enqueue_email(
                user_id=admin_id, template_name="admin_minor_alert", priority=4, force=True,
                custom_vars={
                    "first_name": first_name, "reason": reason.replace("_", " "),
                    "minor_user_id": str(minor.id),
                    "minors_url": f"{get_settings().FRONTEND_URL}/admin/minors",
                },
            )
        except Exception:
            logger.exception("Could not queue minor alert for admin %s", admin_id)


async def in_person_guardian_warnings(db: AsyncSession, event_id: int, user_ids: list[int]) -> list[str]:
    """Admin in-person assignment: minors whose guardian isn't assigned in person."""
    from app.models.participant_action import ActionStatus, ActionType, ParticipantAction
    minors = (await db.execute(
        select(User).where(User.id.in_(user_ids), User.adult_on.isnot(None))
    )).scalars().all()
    minors = [m for m in minors if m.is_minor]
    if not minors:
        return []
    assigned = set(user_ids) | set((await db.execute(
        select(ParticipantAction.user_id).where(
            ParticipantAction.event_id == event_id,
            ParticipantAction.action_type == ActionType.IN_PERSON_ATTENDANCE.value,
            ParticipantAction.status.in_((ActionStatus.PENDING.value, ActionStatus.CONFIRMED.value)),
        )
    )).scalars().all())
    warnings = []
    for m in minors:
        if m.guardian_user_id is None:
            warnings.append(f"Participant {m.id} is under 18 and has no linked guardian.")
        elif m.guardian_user_id not in assigned:
            warnings.append(
                f"Participant {m.id} is under 18; their guardian (participant "
                f"{m.guardian_user_id}) isn't assigned in-person attendance."
            )
    return warnings


async def guardian_for_copies(db: AsyncSession, user: User, custom_vars: Optional[dict] = None,
                              has_attachment: bool = False) -> Optional[User]:
    """
    Who gets a copy of this email to `user`, if anyone: the linked parent/guardian
    of a participant under 18, for essential emails only. Optional emails
    (announcements, future invitations: those carrying a withdrawal link) aren't
    copied, and neither are emails with attachments (e.g. VPN configuration
    files, which are the participant's own access).
    """
    if not user.guardian_user_id or not user.is_minor or has_attachment:
        return None
    if "future_contact_withdraw_url" in (custom_vars or {}):
        return None
    guardian = await db.get(User, user.guardian_user_id)
    if guardian is None or not guardian.email:
        return None
    return guardian
