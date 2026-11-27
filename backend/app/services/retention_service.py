"""
Data retention rules from the public Privacy Policy ("How long we keep it").

Each rule takes dry_run and returns counts; a dry run changes nothing and
reports what a real run would do right now. Counts only, never personal data:
the daily job writes them to a DATA_RETENTION_RUN audit entry.

Rules (periods in app.config, defaults match the policy):
  never_registered_invitees  invitees who never registered, 12 months after the
                             latest invitation, unless they asked for future invitations
  inactive_accounts          2 years without taking part; notice 30 days before deletion
  logs                       security logs + email records older than 1 year
  event_closeout             remind admins to close out events 30 days after they end
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.models.audit_log import AuditLog, EmailEvent, VPNRequest
from app.models.email_queue import EmailQueue, EmailQueueStatus
from app.models.event import Event, EventParticipation, ParticipationStatus
from app.models.password_sync_queue import PasswordSyncQueue
from app.models.user import User

logger = logging.getLogger(__name__)

RUN_ACTION = "DATA_RETENTION_RUN"
DELETE_ACTION = "RETENTION_DELETE"  # one per deleted person: user ID + rule only
CLOSEOUT_REMINDER_ACTION = "EVENT_CLOSEOUT_REMINDER"
CLOSEOUT_REMINDER_EVERY_DAYS = 7
EXEMPT_ROLES = ("admin", "sponsor")  # organizers/referrers (decided 2026-11-26)
DELETION_WARNING_TEMPLATE = "account_deletion_warning"
CLOSEOUT_TEMPLATE = "event_closeout_reminder"


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def months_before(moment: datetime, months: int) -> datetime:
    """Same day-of-month `months` earlier (clamped to the month's last day)."""
    year, month = divmod(moment.month - 1 - months, 12)
    year += moment.year
    month += 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


@dataclass
class _Person:
    """What the rules need to know about one user."""
    user: User
    last_invitation: datetime
    last_took_part: Optional[date]
    has_confirmed: bool
    has_ongoing_invitation: bool


class RetentionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Optional[Settings] = None,
        now: Optional[datetime] = None,
    ):
        self.session = session
        self.settings = settings or get_settings()
        self.now = _utc(now) or datetime.now(timezone.utc)
        self.today = self.now.date()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _event_is_over(event: Event, today: date) -> bool:
        if event.end_date is not None:
            return event.end_date < today
        return bool(event.is_archived)

    @staticmethod
    def _event_end(event: Event) -> Optional[date]:
        if event.end_date is not None:
            return event.end_date
        if event.archived_at is not None:
            return _utc(event.archived_at).date()
        return None

    def _describe(self, user: User) -> _Person:
        invites: list[datetime] = [
            d for d in (
                _utc(user.invite_sent), _utc(user.last_invite_sent),
                _utc(user.invite_reminder_sent), _utc(user.reminder_1_sent_at),
                _utc(user.reminder_2_sent_at), _utc(user.reminder_3_sent_at),
                _utc(user.confirmation_sent_at),
            ) if d
        ]
        last_took_part: Optional[date] = None
        has_confirmed = False
        ongoing = False
        for ep in user.event_participations:
            if ep.invited_at:
                invites.append(_utc(ep.invited_at))
            over = self._event_is_over(ep.event, self.today)
            if ep.status == ParticipationStatus.CONFIRMED.value:
                has_confirmed = True
                end = self._event_end(ep.event)
                if over and end and (last_took_part is None or end > last_took_part):
                    last_took_part = end
            if not over and ep.status in (
                ParticipationStatus.INVITED.value, ParticipationStatus.CONFIRMED.value,
            ):
                ongoing = True
        last_invitation = max(invites) if invites else _utc(user.created_at) or self.now
        return _Person(user, last_invitation, last_took_part, has_confirmed, ongoing)

    def _on_hold(self, user: User) -> bool:
        hold = _utc(user.retention_hold_until)
        return hold is not None and hold > self.now

    async def _load_people(self, *conditions) -> list[_Person]:
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.event_participations).selectinload(EventParticipation.event))
            .where(*conditions)
        )
        return [self._describe(u) for u in result.scalars().all()]

    async def _delete_users(self, users: Iterable[User], rule: str) -> int:
        """Delete each person and record a RETENTION_DELETE audit entry holding only
        their (now unlinkable) user ID and the rule, so "was this person deleted,
        and when?" can be answered later. Kept like DATA_RETENTION_RUN entries."""
        from app.services.audit_service import AuditService
        from app.services.participant_service import ParticipantService
        service = ParticipantService(self.session)
        audit = AuditService(self.session)
        deleted = 0
        for user_id in [u.id for u in users]:  # ids first: commits expire loaded rows
            try:
                if await service.delete_participant(user_id):
                    deleted += 1
                    await audit.log(
                        action=DELETE_ACTION,
                        resource_type="USER",
                        resource_id=user_id,
                        details={"target_user_id": user_id, "rule": rule},
                    )
            except Exception:
                logger.exception("Retention deletion failed for user %s", user_id)
                await self.session.rollback()
        return deleted

    # --------------------------------------------------- rule: never registered

    async def never_registered_candidates(self) -> list[User]:
        cutoff = months_before(self.now, self.settings.RETENTION_INVITEE_MONTHS)
        people = await self._load_people(
            User.role == "invitee",
            User.password_hash.is_(None),
            User.confirmed.in_(("NO", "UNKNOWN")),
        )
        return [
            p.user for p in people
            if not p.has_confirmed
            and not p.has_ongoing_invitation
            and p.user.future_contact_consent is not True
            and not self._on_hold(p.user)
            and p.last_invitation < cutoff
        ]

    async def purge_never_registered_invitees(self, dry_run: bool) -> dict:
        candidates = await self.never_registered_candidates()
        # A dry run reports what a real run would delete right now.
        deleted = len(candidates) if dry_run else await self._delete_users(
            candidates, rule="never_registered_invitees")
        return {"candidates": len(candidates), "deleted": deleted}

    # --------------------------------------------------- rule: inactive accounts

    async def _inactive_people(self) -> tuple[list[_Person], list[User]]:
        """(inactive and not excluded, previously warned but no longer due)."""
        months = self.settings.RETENTION_INACTIVE_ACCOUNT_MONTHS
        cutoff = months_before(self.now, months)
        cutoff_day = cutoff.date()
        never_registered = {u.id for u in await self.never_registered_candidates()}

        people = await self._load_people(User.role.notin_(EXEMPT_ROLES))
        inactive: list[_Person] = []
        cancelled: list[User] = []
        for p in people:
            u = p.user
            if u.id in never_registered:
                continue  # handled by the 12-month rule
            if p.last_took_part is not None:
                is_inactive = p.last_took_part < cutoff_day
            else:
                created = _utc(u.created_at) or self.now
                is_inactive = created < cutoff and p.last_invitation < cutoff
            last_login = _utc(u.last_login_at)
            excluded = (
                p.has_ongoing_invitation
                or self._on_hold(u)
                or (last_login is not None and last_login >= cutoff)
            )
            if is_inactive and not excluded:
                inactive.append(p)
            elif u.deletion_warning_sent_at is not None:
                cancelled.append(u)
        return inactive, cancelled

    async def process_inactive_accounts(self, dry_run: bool) -> dict:
        warning_days = self.settings.RETENTION_INACTIVE_WARNING_DAYS
        inactive, cancelled = await self._inactive_people()

        to_warn = [p.user for p in inactive if p.user.deletion_warning_sent_at is None]
        to_delete = [
            p.user for p in inactive
            if p.user.deletion_warning_sent_at is not None
            and _utc(p.user.deletion_warning_sent_at) + timedelta(days=warning_days) <= self.now
        ]
        counts = {
            "inactive": len(inactive),
            "warnings_sent": len(to_warn),
            "deleted": len(to_delete),
            "warnings_cancelled": len(cancelled),
        }
        if dry_run:
            return counts

        warn = [(u.id, u.first_name) for u in to_warn]
        for user in cancelled:
            user.deletion_warning_sent_at = None
        await self.session.commit()

        counts["deleted"] = await self._delete_users(to_delete, rule="inactive_accounts")

        sent = 0
        for user_id, first_name in warn:
            if await self._send_deletion_warning(user_id, first_name, warning_days):
                sent += 1
        counts["warnings_sent"] = sent
        return counts

    async def _send_deletion_warning(self, user_id: int, first_name: str, warning_days: int) -> bool:
        from sqlalchemy import update
        from app.services.email_queue_service import EmailQueueService
        delete_on = (self.now + timedelta(days=warning_days)).date()
        await self.session.execute(
            update(User).where(User.id == user_id).values(deletion_warning_sent_at=self.now)
        )
        await self.session.commit()
        try:
            await EmailQueueService(self.session).enqueue_email(
                user_id=user_id,
                template_name=DELETION_WARNING_TEMPLATE,
                priority=3,
                force=True,
                custom_vars={
                    "first_name": first_name,
                    "deletion_date": delete_on.strftime("%B %d, %Y").replace(" 0", " "),
                    "login_url": f"{self.settings.FRONTEND_URL}/login",
                    "contact_email": self.settings.PRIVACY_CONTACT_EMAIL,
                    "privacy_policy_url": self.settings.PRIVACY_POLICY_URL,
                },
            )
        except Exception:
            # Notice recorded as attempted; deletion still waits the full period.
            logger.exception("Could not queue deletion notice for user %s", user_id)
            return False
        return True

    # ------------------------------------------------------------- rule: logs

    def _log_targets(self, cutoff: datetime):
        final = (EmailQueueStatus.SENT, EmailQueueStatus.FAILED, EmailQueueStatus.CANCELLED)
        return [
            ("audit_logs", AuditLog, (
                AuditLog.created_at < cutoff, AuditLog.action.notin_((RUN_ACTION, DELETE_ACTION)),
            )),
            ("email_events", EmailEvent, (EmailEvent.created_at < cutoff,)),
            ("vpn_requests", VPNRequest, (VPNRequest.requested_at < cutoff,)),
            ("email_queue", EmailQueue, (EmailQueue.created_at < cutoff, EmailQueue.status.in_(final))),
            ("password_sync_queue", PasswordSyncQueue, (
                PasswordSyncQueue.synced.is_(True), PasswordSyncQueue.synced_at < cutoff,
            )),
        ]

    async def purge_old_logs(self, dry_run: bool) -> dict:
        cutoff = self.now - timedelta(days=self.settings.RETENTION_LOG_DAYS)
        batch = max(1, self.settings.RETENTION_BATCH_SIZE)
        counts: dict[str, int] = {}
        for key, model, conds in self._log_targets(cutoff):
            if dry_run:
                counts[key] = (await self.session.execute(
                    select(func.count()).select_from(model).where(*conds)
                )).scalar() or 0
                continue
            total = 0
            while True:
                ids = select(model.id).where(*conds).limit(batch).scalar_subquery()
                res = await self.session.execute(
                    delete(model).where(model.id.in_(ids))
                    .execution_options(synchronize_session=False)
                )
                await self.session.commit()
                n = res.rowcount or 0
                total += n
                if n < batch:
                    break
            counts[key] = total
        return counts

    # --------------------------------------------------- rule: event close-out

    async def overdue_events(self) -> list[Event]:
        cutoff = self.today - timedelta(days=self.settings.RETENTION_EVENT_CLOSEOUT_DAYS)
        result = await self.session.execute(
            select(Event).where(
                Event.end_date.isnot(None),
                Event.end_date < cutoff,
                Event.is_archived.isnot(True),
            ).order_by(Event.end_date)
        )
        return list(result.scalars().all())

    async def _reminded_recently(self, event_id: int) -> bool:
        since = self.now - timedelta(days=CLOSEOUT_REMINDER_EVERY_DAYS)
        result = await self.session.execute(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.action == CLOSEOUT_REMINDER_ACTION,
                AuditLog.resource_type == "EVENT",
                AuditLog.resource_id == event_id,
                AuditLog.created_at >= since,
            )
        )
        return (result.scalar() or 0) > 0

    async def event_closeout_reminders(self, dry_run: bool) -> dict:
        events = await self.overdue_events()
        due = [e for e in events if not await self._reminded_recently(e.id)]
        counts = {"overdue_events": len(events), "reminders_sent": len(due)}
        if dry_run or not due:
            return counts

        from app.services.audit_service import AuditService
        from app.services.email_queue_service import EmailQueueService
        admins = [
            (a.id, a.first_name) for a in (await self.session.execute(
                select(User).where(User.role == "admin", User.is_active.is_(True))
            )).scalars().all()
        ]
        due = [(e.id, e.name, e.end_date) for e in due]
        queue = EmailQueueService(self.session)
        for event_id, event_name, end_date in due:
            days_over = (self.today - end_date).days
            for admin_id, admin_first_name in admins:
                try:
                    await queue.enqueue_email(
                        user_id=admin_id,
                        template_name=CLOSEOUT_TEMPLATE,
                        priority=4,
                        force=True,
                        custom_vars={
                            "first_name": admin_first_name,
                            "event_name": event_name,
                            "event_end_date": end_date.isoformat(),
                            "days_since_end": str(days_over),
                            "events_url": f"{self.settings.FRONTEND_URL}/admin/events",
                        },
                    )
                except Exception:
                    logger.exception("Could not queue close-out reminder for event %s", event_id)
            await AuditService(self.session).log(
                action=CLOSEOUT_REMINDER_ACTION,
                resource_type="EVENT",
                resource_id=event_id,
                details={"days_since_end": days_over, "admins_notified": len(admins)},
            )
        return counts

    # --------------------------------------------------------------- all rules

    async def run_all(self, dry_run: bool) -> dict:
        """Run every rule in order. One failing rule doesn't stop the others."""
        results: dict = {"dry_run": dry_run}
        steps = (
            ("never_registered_invitees", self.purge_never_registered_invitees),
            ("inactive_accounts", self.process_inactive_accounts),
            ("logs", self.purge_old_logs),
            ("event_closeout", self.event_closeout_reminders),
        )
        for key, step in steps:
            try:
                results[key] = await step(dry_run)
            except Exception as exc:
                logger.exception("Retention step %s failed", key)
                await self.session.rollback()
                results[key] = {"error": type(exc).__name__}
        return results
