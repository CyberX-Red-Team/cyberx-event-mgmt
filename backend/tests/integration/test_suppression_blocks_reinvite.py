"""People on the do-not-invite list can't be re-invited by any path, including
while their account still exists (before the 12-month deletion)."""
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import func, select

from app.models.email_queue import EmailQueue
from app.models.invite_suppression import InviteSuppression
from app.services.invite_suppression_service import SUPPRESSED_MESSAGE, email_hmac
from tests.personal_data_seed import make_user

pytestmark = pytest.mark.asyncio


async def _suppressed_user(db, sponsor_id=None, role="invitee"):
    user = await make_user(db, "nope@example.org", "No", "Thanks", role=role, sponsor_id=sponsor_id,
                           confirmed="NO", future_contact_consent=False)
    db.add(InviteSuppression(email_hmac=email_hmac(user.email)))
    await db.commit()
    return user


async def _queued(db, user_id):
    return (await db.execute(
        select(func.count()).select_from(EmailQueue).where(EmailQueue.user_id == user_id)
    )).scalar()


async def test_admin_resend_refused(authenticated_admin_client, db_session, active_event):
    user = await _suppressed_user(db_session)
    resp = await authenticated_admin_client.post(f"/api/admin/participants/{user.id}/resend-invitation")
    assert resp.status_code == 409
    assert resp.json()["detail"] == SUPPRESSED_MESSAGE
    assert await _queued(db_session, user.id) == 0


async def test_referrer_resend_refused(authenticated_sponsor_client, db_session, active_event, sponsor_user):
    user = await _suppressed_user(db_session, sponsor_id=sponsor_user.id)
    resp = await authenticated_sponsor_client.post(f"/api/sponsors/my-invitees/{user.id}/resend-invite")
    assert resp.status_code == 409
    assert resp.json()["detail"] == SUPPRESSED_MESSAGE
    assert await _queued(db_session, user.id) == 0


async def test_resend_works_again_after_removal(authenticated_admin_client, db_session, active_event):
    user = await _suppressed_user(db_session)
    rm = await authenticated_admin_client.post("/api/admin/invite-suppressions/remove",
                                               json={"email": user.email})
    assert rm.json()["removed"] is True
    resp = await authenticated_admin_client.post(f"/api/admin/participants/{user.id}/resend-invitation")
    assert resp.status_code == 200, resp.text
    assert await _queued(db_session, user.id) == 1


async def test_automatic_run_skips_suppressed_even_when_staff(db_session, monkeypatch):
    """Sponsors are exempt from consent gating, but not from the do-not-invite list."""
    from app.tasks import invitation_emails
    from tests.personal_data_seed import make_event

    event = await make_event(db_session, "Run", is_active=True, registration_open=True)
    blocked = await _suppressed_user(db_session, role="sponsor")
    fine = await make_user(db_session, "ok@example.org", role="sponsor")

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(invitation_emails, "AsyncSessionLocal", fake_session)
    await invitation_emails.send_invitations_to_unknown_participants(event.id, event.name, test_mode=True)

    assert await _queued(db_session, blocked.id) == 0
    assert await _queued(db_session, fine.id) == 1


async def test_reset_workflow_does_not_reinvite(db_session, active_event):
    from app.services.participant_service import ParticipantService
    user = await _suppressed_user(db_session)
    result = await ParticipantService(db_session).reset_workflow_state(user.id)
    assert result is not None  # the reset itself still happens
    assert await _queued(db_session, user.id) == 0
