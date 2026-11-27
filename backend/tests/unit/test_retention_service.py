"""Retention rules: just inside each window kept, just outside deleted; exclusions;
dry run == real counts and changes nothing; daily job is idempotent."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit_log import AuditLog, EmailEvent, VPNRequest
from app.models.email_queue import EmailQueue
from app.models.event import EventParticipation
from app.models.password_sync_queue import PasswordSyncQueue
from app.models.user import User
from app.services.retention_service import (
    CLOSEOUT_TEMPLATE, DELETION_WARNING_TEMPLATE, RUN_ACTION, RetentionService, months_before,
)
from app.utils.security import hash_password
from tests.personal_data_seed import make_event, make_user

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = timedelta(days=1)


def svc(db, settings, now=NOW, **overrides):
    if overrides:
        settings = settings.model_copy(update=overrides)
    return RetentionService(db, settings=settings, now=now)


async def ids(db):
    return set((await db.execute(select(User.id))).scalars().all())


async def invite(db, user, event, when, status="invited"):
    db.add(EventParticipation(user_id=user.id, event_id=event.id, invited_at=when, status=status))
    await db.commit()


# ------------------------------------------------------------ never registered

@pytest.fixture
async def past_event(db_session):
    return await make_event(db_session, "Past Event", end_date=(NOW - timedelta(days=500)).date(),
                            is_archived=True)


async def _invitee(db, email, event, invited_at, **kw):
    user = await make_user(db, email, created_at=invited_at, **kw)
    await invite(db, user, event, invited_at, status=kw.pop("_status", "invited"))
    return user


async def test_never_registered_window(db_session, test_settings, past_event):
    cutoff = months_before(NOW, 12)
    outside = await _invitee(db_session, "out@example.org", past_event, cutoff - DAY)
    inside = await _invitee(db_session, "in@example.org", past_event, cutoff + DAY)

    result = await svc(db_session, test_settings).purge_never_registered_invitees(dry_run=False)

    remaining = await ids(db_session)
    assert outside.id not in remaining
    assert inside.id in remaining
    assert result == {"candidates": 1, "deleted": 1}


async def test_never_registered_exclusions(db_session, test_settings, past_event):
    old = months_before(NOW, 12) - 10 * DAY
    consented = await _invitee(db_session, "c@example.org", past_event, old,
                               future_contact_consent=True)
    registered = await _invitee(db_session, "r@example.org", past_event, old,
                                password_hash=hash_password("x"))
    held = await _invitee(db_session, "h@example.org", past_event, old,
                          retention_hold_until=NOW + 30 * DAY)
    took_part = await make_user(db_session, "t@example.org", created_at=old)
    await invite(db_session, took_part, past_event, old, status="confirmed")
    declined_no_choice = await _invitee(db_session, "d@example.org", past_event, old,
                                        confirmed="NO", future_contact_consent=False)

    service = svc(db_session, test_settings)
    candidates = {u.id for u in await service.never_registered_candidates()}
    assert candidates == {declined_no_choice.id}
    for kept in (consented, registered, held, took_part):
        assert kept.id not in candidates


async def test_dry_run_matches_real_run_and_changes_nothing(db_session, test_settings, past_event):
    old = months_before(NOW, 12) - DAY
    for i in range(3):
        await _invitee(db_session, f"p{i}@example.org", past_event, old)
    before = await ids(db_session)

    dry = await svc(db_session, test_settings).run_all(dry_run=True)
    assert await ids(db_session) == before

    real = await svc(db_session, test_settings).run_all(dry_run=False)
    assert dry["never_registered_invitees"] == real["never_registered_invitees"] == {
        "candidates": 3, "deleted": 3
    }
    assert dry["logs"] == real["logs"]
    assert dry["inactive_accounts"] == real["inactive_accounts"]


# ----------------------------------------------------------- inactive accounts

async def _operator(db, email, ended_days_ago, **kw):
    created = NOW - timedelta(days=ended_days_ago + 60)
    user = await make_user(db, email, password_hash=hash_password("x"), created_at=created, **kw)
    event = await make_event(db, f"Event for {email}",
                             end_date=(NOW - timedelta(days=ended_days_ago)).date(), is_archived=True)
    await invite(db, user, event, created, status="confirmed")
    return user


async def test_inactive_window_and_exclusions(db_session, test_settings):
    two_years_days = (NOW.date() - months_before(NOW, 24).date()).days
    inactive = await _operator(db_session, "old@example.org", two_years_days + 1)
    recent = await _operator(db_session, "recent@example.org", two_years_days - 1)
    sponsor = await _operator(db_session, "sp@example.org", two_years_days + 30, role="sponsor")
    admin = await _operator(db_session, "ad@example.org", two_years_days + 30, role="admin")
    logged_in = await _operator(db_session, "li@example.org", two_years_days + 30,
                                last_login_at=NOW - 30 * DAY)
    held = await _operator(db_session, "held@example.org", two_years_days + 30,
                           retention_hold_until=NOW + DAY)

    inactive_people, _ = await svc(db_session, test_settings)._inactive_people()
    assert {p.user.id for p in inactive_people} == {inactive.id}
    for u in (recent, sponsor, admin, logged_in, held):
        assert u.id not in {p.user.id for p in inactive_people}


async def test_inactive_warning_then_deletion_after_notice_period(db_session, test_settings):
    user = await _operator(db_session, "old@example.org", 900)

    first = await svc(db_session, test_settings).process_inactive_accounts(dry_run=False)
    assert first["warnings_sent"] == 1 and first["deleted"] == 0
    db_session.expunge_all()
    warned = await db_session.get(User, user.id)
    assert warned.deletion_warning_sent_at is not None
    queued = (await db_session.execute(
        select(EmailQueue).where(EmailQueue.template_name == DELETION_WARNING_TEMPLATE)
    )).scalars().all()
    assert len(queued) == 1 and queued[0].custom_vars["deletion_date"]

    # Running again the same day sends nothing new (idempotent)
    again = await svc(db_session, test_settings).process_inactive_accounts(dry_run=False)
    assert again["warnings_sent"] == 0 and again["deleted"] == 0

    # Day 29: still waiting. Day 30: deleted.
    early = await svc(db_session, test_settings, now=NOW + 29 * DAY).process_inactive_accounts(False)
    assert early["deleted"] == 0 and user.id in await ids(db_session)
    late = await svc(db_session, test_settings, now=NOW + 30 * DAY).process_inactive_accounts(False)
    assert late["deleted"] == 1 and user.id not in await ids(db_session)


async def test_signing_in_cancels_pending_deletion(db_session, test_settings):
    user = await _operator(db_session, "old@example.org", 900)
    await svc(db_session, test_settings).process_inactive_accounts(dry_run=False)

    db_session.expunge_all()
    u = await db_session.get(User, user.id)
    u.last_login_at = NOW + DAY
    await db_session.commit()

    later = await svc(db_session, test_settings, now=NOW + 40 * DAY).process_inactive_accounts(False)
    assert later["deleted"] == 0 and later["warnings_cancelled"] == 1
    db_session.expunge_all()
    assert (await db_session.get(User, user.id)).deletion_warning_sent_at is None


async def test_create_session_records_login_and_cancels_notice(db_session):
    from app.services.auth_service import AuthService
    user = await make_user(db_session, "li@example.org", deletion_warning_sent_at=NOW - DAY)
    await AuthService(db_session).create_session(user.id)
    db_session.expunge_all()
    u = await db_session.get(User, user.id)
    assert u.last_login_at is not None and u.deletion_warning_sent_at is None


# ------------------------------------------------------------------------ logs

async def test_log_purge_window_and_batching(db_session, test_settings):
    old = NOW - timedelta(days=366)
    new = NOW - timedelta(days=364)
    db_session.add_all(
        [AuditLog(action="LOGIN_SUCCESS", created_at=old) for _ in range(5)]
        + [AuditLog(action="LOGIN_SUCCESS", created_at=new),
           AuditLog(action=RUN_ACTION, created_at=old, details={"dry_run": True})]
        + [EmailEvent(email_to="a@example.org", event_type="delivered", created_at=old),
           EmailEvent(email_to="a@example.org", event_type="delivered", created_at=new),
           VPNRequest(key_type="cyber", requested_at=old),
           EmailQueue(template_name="t", recipient_email="a@example.org", status="sent", created_at=old),
           EmailQueue(template_name="t", recipient_email="a@example.org", status="pending", created_at=old),
           PasswordSyncQueue(username="u", operation="create_user", synced=True, synced_at=old),
           PasswordSyncQueue(username="u", operation="create_user", synced=False)]
    )
    await db_session.commit()

    service = svc(db_session, test_settings, RETENTION_BATCH_SIZE=2)
    dry = await service.purge_old_logs(dry_run=True)
    real = await service.purge_old_logs(dry_run=False)
    assert dry == real == {
        "audit_logs": 5, "email_events": 1, "vpn_requests": 1, "email_queue": 1,
        "password_sync_queue": 1,
    }

    async def count(model, *where):
        return (await db_session.execute(select(func.count()).select_from(model).where(*where))).scalar()

    assert await count(AuditLog) == 2  # the recent login + the retention run record
    assert await count(AuditLog, AuditLog.action == RUN_ACTION) == 1
    assert await count(EmailQueue) == 1  # pending email kept
    assert await count(PasswordSyncQueue) == 1  # unsynced kept


# ------------------------------------------------------------ event close-out

async def test_event_closeout_reminder_once_per_week(db_session, test_settings, admin_user):
    overdue = await make_event(db_session, "Overdue", end_date=(NOW - 31 * DAY).date())
    await make_event(db_session, "Recent", end_date=(NOW - 29 * DAY).date())
    await make_event(db_session, "Archived", end_date=(NOW - 90 * DAY).date(), is_archived=True)

    first = await svc(db_session, test_settings).event_closeout_reminders(dry_run=False)
    assert first == {"overdue_events": 1, "reminders_sent": 1}
    emails = (await db_session.execute(
        select(EmailQueue).where(EmailQueue.template_name == CLOSEOUT_TEMPLATE)
    )).scalars().all()
    assert [e.user_id for e in emails] == [admin_user.id]
    assert emails[0].custom_vars["event_name"] == overdue.name

    second = await svc(db_session, test_settings).event_closeout_reminders(dry_run=False)
    assert second == {"overdue_events": 1, "reminders_sent": 0}


# ------------------------------------------------------------------- daily job

async def test_job_disabled_runs_dry_and_records_counts_only(db_session, test_settings, past_event,
                                                             monkeypatch):
    from app.tasks import data_retention

    old = months_before(NOW, 12) - DAY
    victim = await _invitee(db_session, "victim@example.org", past_event, old)

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(data_retention, "AsyncSessionLocal", fake_session)
    monkeypatch.setattr(data_retention, "get_settings",
                        lambda: test_settings.model_copy(update={"RETENTION_ENABLED": False}))

    await data_retention.data_retention_job()

    assert victim.id in await ids(db_session)
    entry = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == RUN_ACTION)
    )).scalar_one()
    assert entry.details["dry_run"] is True
    assert entry.details["never_registered_invitees"]["candidates"] == 1
    assert "victim@example.org" not in str(entry.details)


async def test_real_run_is_idempotent(db_session, test_settings, past_event):
    old = months_before(NOW, 12) - DAY
    await _invitee(db_session, "a@example.org", past_event, old)
    await _operator(db_session, "op@example.org", 900)

    first = await svc(db_session, test_settings).run_all(dry_run=False)
    second = await svc(db_session, test_settings).run_all(dry_run=False)
    assert first["never_registered_invitees"]["deleted"] == 1
    assert second["never_registered_invitees"]["deleted"] == 0
    assert first["inactive_accounts"]["warnings_sent"] == 1
    assert second["inactive_accounts"]["warnings_sent"] == 0
    assert second["inactive_accounts"]["deleted"] == 0


def test_months_before_clamps_day():
    assert months_before(datetime(2027, 3, 31, tzinfo=timezone.utc), 1).day == 28
    assert months_before(datetime(2027, 1, 15, tzinfo=timezone.utc), 12).year == 2026
