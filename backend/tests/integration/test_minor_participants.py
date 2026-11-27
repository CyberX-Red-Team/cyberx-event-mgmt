"""Participants aged 16-17: registration, guardian linking and consent, gating,
suspension, in-person rules, emails, and the turning-18 job.

Assert DB state, not only status codes. One HTTP client; switch users by
logging in (never several pre-authenticated clients sharing one object).
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit_log import AuditLog
from app.models.email_queue import EmailQueue
from app.models.event import EventParticipation
from app.models.guardian_consent import GuardianConsent
from app.models.participant_action import ParticipantAction
from app.models.password_sync_queue import PasswordSyncQueue
from app.models.user import User
from app.services import minor_service
from app.services.workflow_service import WorkflowService
from app.utils.security import hash_password
from tests.personal_data_seed import make_user

pytestmark = pytest.mark.asyncio

TODAY = date.today()
MINOR_BIRTH = {"birth_year": TODAY.year - 17, "birth_month": TODAY.month}   # 17 now
UNDER_16_BIRTH = {"birth_year": TODAY.year - 15, "birth_month": TODAY.month}


@pytest.fixture
def workflow_calls(monkeypatch):
    calls = []

    async def fake(self, trigger_event, user_id, custom_vars=None, force=False):
        calls.append((str(trigger_event), user_id))
        return 1

    monkeypatch.setattr(WorkflowService, "trigger_workflow", fake)
    return calls


async def _reload(db, model, pk):
    db.expunge_all()
    return await db.get(model, pk)


async def login(client, email, password="pw-12345"):
    client.cookies.clear()
    resp = await client.post("/api/auth/login", json={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    # Secure cookie isn't kept over http by httpx; set it like the conftest fixtures do
    client.cookies.set("session_token", resp.cookies.get("session_token"))


async def guardian_for(db, event, email="parent@example.org", confirmed=True, **kw):
    g = await make_user(db, email, "Pat", "Parent", password_hash=hash_password("pw-12345"),
                        confirmed="YES" if confirmed else "UNKNOWN", **kw)
    db.add(EventParticipation(user_id=g.id, event_id=event.id,
                              status="confirmed" if confirmed else "invited"))
    await db.commit()
    return g


async def invited_minor(db, event, email="kid@example.org"):
    m = await make_user(db, email, "Kim", "Kid", confirmation_code=f"code-{email}")
    db.add(EventParticipation(user_id=m.id, event_id=event.id, status="invited"))
    await db.commit()
    return m


async def accept_as_minor(client, minor, guardian_email="parent@example.org", birth=MINOR_BIRTH):
    return await client.post("/api/public/confirm/accept", json={
        "confirmation_code": minor.confirmation_code, "terms_accepted": True,
        "terms_version": "1.0", "is_adult": False, "guardian_email": guardian_email, **birth,
    })


async def consent(client, minor_id, **overrides):
    body = {"relationship": "parent", "accept_terms": True, "confirm_consent": True,
            "guardian_name_typed": "Pat Parent", "optional_email_consent": False, **overrides}
    return await client.post(f"/api/guardian/minors/{minor_id}/consent", json=body)


async def count(db, model, *where):
    return (await db.execute(select(func.count()).select_from(model).where(*where))).scalar()


# ---------------------------------------------------------------- registration

async def test_under_16_rejected_and_nothing_stored(client, db_session, active_event):
    minor = await invited_minor(db_session, active_event)
    before = await _reload(db_session, User, minor.id)
    snapshot = {c: getattr(before, c) for c in ("confirmed", "terms_accepted", "birth_year_month",
                                                "adult_on", "age_attestation", "guardian_email_pending",
                                                "future_contact_consent")}
    resp = await accept_as_minor(client, minor, birth=UNDER_16_BIRTH)
    assert resp.status_code == 400
    assert resp.json()["detail"] == minor_service.UNDER_16_MESSAGE
    after = await _reload(db_session, User, minor.id)
    assert {c: getattr(after, c) for c in snapshot} == snapshot
    ep = (await db_session.execute(select(EventParticipation))).scalar_one()
    assert ep.status == "invited"


async def test_minor_registers_but_isnt_activated_until_consent(client, db_session, active_event,
                                                                workflow_calls):
    guardian = await guardian_for(db_session, active_event)
    minor = await invited_minor(db_session, active_event)

    resp = await accept_as_minor(client, minor)
    assert resp.status_code == 200, resp.text
    assert resp.json()["awaiting_guardian_consent"] is True and resp.json()["guardian_linked"] is True

    m = await _reload(db_session, User, minor.id)
    assert m.terms_accepted and m.confirmed == "YES"
    assert m.adult_on == date(TODAY.year + 1, TODAY.month, 1)
    assert m.guardian_user_id == guardian.id and m.guardian_link_status == "pending"
    # No credentials, Keycloak sync, Discord invite or credentials email yet
    assert m.pandas_username is None and m.password_hash is None
    assert await count(db_session, PasswordSyncQueue) == 0
    assert workflow_calls == []
    ep = (await db_session.execute(
        select(EventParticipation).where(EventParticipation.user_id == minor.id))).scalar_one()
    assert ep.status == "confirmed" and ep.activated_at is None
    # Guardian asked for consent
    assert await count(db_session, EmailQueue, EmailQueue.user_id == guardian.id,
                       EmailQueue.template_name == "guardian_consent_needed") == 1

    # Guardian consents -> activation runs once
    await login(client, guardian.email)
    resp = await consent(client, minor.id)
    assert resp.status_code == 200, resp.text
    m = await _reload(db_session, User, minor.id)
    assert m.pandas_username and m.password_hash and m.guardian_link_status == "confirmed"
    assert await count(db_session, PasswordSyncQueue, PasswordSyncQueue.operation == "create_user") == 1
    assert [(c[0].lower().endswith("user_confirmed"), c[1]) for c in workflow_calls] == [(True, minor.id)]

    # Consenting again doesn't activate a second time
    resp = await consent(client, minor.id)
    assert resp.status_code == 200
    assert await count(db_session, PasswordSyncQueue, PasswordSyncQueue.operation == "create_user") == 1
    assert len(workflow_calls) == 1


async def test_consent_rejected_if_guardian_not_confirmed_for_event(client, db_session, active_event,
                                                                    workflow_calls):
    guardian = await guardian_for(db_session, active_event, confirmed=False)
    minor = await invited_minor(db_session, active_event)
    m = await _reload(db_session, User, minor.id)
    m.guardian_user_id, m.guardian_link_status = guardian.id, "pending"
    m.adult_on = date(TODAY.year + 1, TODAY.month, 1)
    await db_session.commit()
    ep = (await db_session.execute(
        select(EventParticipation).where(EventParticipation.user_id == minor.id))).scalar_one()
    ep.status = "confirmed"
    await db_session.commit()

    await login(client, guardian.email)
    resp = await consent(client, minor.id)
    assert resp.status_code == 400
    assert await count(db_session, GuardianConsent) == 0
    assert workflow_calls == []


async def test_unmatched_guardian_email_creates_no_link_and_expires(client, db_session, active_event,
                                                                    test_settings):
    minor = await invited_minor(db_session, active_event)
    resp = await accept_as_minor(client, minor, guardian_email="nobody@example.org")
    assert resp.status_code == 200 and resp.json()["guardian_linked"] is False
    m = await _reload(db_session, User, minor.id)
    assert m.guardian_user_id is None and m.guardian_email_pending == "nobody@example.org"

    later = datetime.now(timezone.utc) + timedelta(days=31)
    from app.services.retention_service import RetentionService
    result = await RetentionService(db_session, settings=test_settings, now=later).minor_housekeeping(False)
    assert result["guardian_emails_discarded"] == 1
    m = await _reload(db_session, User, minor.id)
    assert m.guardian_email_pending is None and m.guardian_email_pending_at is None


async def test_guardian_registering_later_links_waiting_minor(client, db_session, active_event,
                                                              workflow_calls):
    minor = await invited_minor(db_session, active_event)
    await accept_as_minor(client, minor, guardian_email="Late.Parent@example.org")
    late = await make_user(db_session, "late.parent@example.org", "Lee", "Parent",
                           confirmation_code="code-late")
    db_session.add(EventParticipation(user_id=late.id, event_id=active_event.id, status="invited"))
    await db_session.commit()

    resp = await client.post("/api/public/confirm/accept", json={
        "confirmation_code": "code-late", "terms_accepted": True, "terms_version": "1.0",
        "is_adult": True,
    })
    assert resp.status_code == 200, resp.text
    m = await _reload(db_session, User, minor.id)
    assert m.guardian_user_id == late.id and m.guardian_link_status == "pending"
    assert m.guardian_email_pending is None


# ------------------------------------------------- relationship, not a role

async def _linked_and_cleared(client, db, event):
    guardian = await guardian_for(db, event)
    minor = await invited_minor(db, event)
    await accept_as_minor(client, minor)
    await login(client, guardian.email)
    resp = await consent(client, minor.id)
    assert resp.status_code == 200, resp.text
    return guardian, minor


async def test_linking_never_grants_roles_or_referrer_access(client, db_session, active_event,
                                                             invitee_role, workflow_calls):
    guardian = await guardian_for(db_session, active_event, role_id=invitee_role.id)
    before = await _reload(db_session, User, guardian.id)
    role, role_id, overrides = before.role, before.role_id, before.permission_overrides
    minor = await invited_minor(db_session, active_event)
    await accept_as_minor(client, minor)
    await login(client, guardian.email)
    assert (await consent(client, minor.id)).status_code == 200

    g = await _reload(db_session, User, guardian.id)
    assert (g.role, g.role_id, g.permission_overrides) == (role, role_id, overrides)
    await login(client, guardian.email)
    for path in ("/api/sponsors/my-invitees", "/api/sponsors/my-invitees/stats",
                 f"/api/sponsors/my-invitees/{minor.id}"):
        assert (await client.get(path)).status_code == 403, path


async def test_guardian_sees_only_linked_minors(client, db_session, active_event, workflow_calls):
    guardian, minor = await _linked_and_cleared(client, db_session, active_event)
    stranger = await make_user(db_session, "other.kid@example.org")
    await login(client, guardian.email)
    assert (await client.get(f"/api/guardian/minors/{minor.id}")).status_code == 200
    for path in (f"/api/guardian/minors/{stranger.id}", f"/api/guardian/minors/{guardian.id}"):
        assert (await client.get(path)).status_code == 403
    assert (await consent(client, stranger.id)).status_code == 403
    listed = (await client.get("/api/guardian/minors")).json()["minors"]
    assert [m["id"] for m in listed] == [minor.id]


async def test_not_my_child_clears_link(client, db_session, active_event, workflow_calls):
    guardian = await guardian_for(db_session, active_event)
    minor = await invited_minor(db_session, active_event)
    await accept_as_minor(client, minor)
    await login(client, guardian.email)
    assert (await client.post(f"/api/guardian/minors/{minor.id}/reject")).status_code == 200
    m = await _reload(db_session, User, minor.id)
    assert m.guardian_user_id is None and m.guardian_link_status is None
    assert (await client.get(f"/api/guardian/minors/{minor.id}")).status_code == 403


# ------------------------------------------------------------ suspension

async def _in_person(db, user, event, status="confirmed"):
    db.add(ParticipantAction(user_id=user.id, event_id=event.id, action_type="in_person_attendance",
                             title="In person", status=status))
    u = await db.get(User, user.id)
    u.confirmed_in_person = status == "confirmed"
    await db.commit()


async def test_withdrawal_suspends_access_and_in_person(client, db_session, active_event, workflow_calls):
    guardian, minor = await _linked_and_cleared(client, db_session, active_event)
    await _in_person(db_session, guardian, active_event)
    await _in_person(db_session, minor, active_event)

    resp = await client.post(f"/api/guardian/minors/{minor.id}/withdraw")
    assert resp.status_code == 200
    m = await _reload(db_session, User, minor.id)
    assert m.confirmed_in_person is False
    assert not await minor_service.participant_is_cleared(db_session, m, active_event)
    ep = (await db_session.execute(
        select(EventParticipation).where(EventParticipation.user_id == minor.id))).scalar_one()
    assert ep.suspended_at is not None
    assert await count(db_session, PasswordSyncQueue, PasswordSyncQueue.operation == "disable_user") == 1
    action = (await db_session.execute(
        select(ParticipantAction).where(ParticipantAction.user_id == minor.id))).scalar_one()
    assert action.status == "cancelled"
    # Minor notified (and guardian copied)
    sent = (await db_session.execute(
        select(EmailQueue).where(EmailQueue.template_name == "minor_access_suspended"))).scalars().all()
    assert {e.recipient_email for e in sent} == {minor.email, guardian.email}

    # Consent again resumes without new credentials
    assert (await consent(client, minor.id)).status_code == 200
    assert await minor_service.participant_is_cleared(db_session, await _reload(db_session, User, minor.id),
                                                      active_event)
    assert await count(db_session, PasswordSyncQueue, PasswordSyncQueue.operation == "enable_user") == 1
    assert len(workflow_calls) == 1


async def test_guardian_declining_event_suspends_minor(client, db_session, active_event, workflow_calls):
    guardian, minor = await _linked_and_cleared(client, db_session, active_event)
    g = await _reload(db_session, User, guardian.id)
    g.confirmation_code = "code-guardian"
    await db_session.commit()
    resp = await client.post("/api/public/confirm/decline",
                             json={"confirmation_code": "code-guardian"})
    assert resp.status_code == 200
    assert not await minor_service.participant_is_cleared(
        db_session, await _reload(db_session, User, minor.id), active_event)


async def test_guardian_removed_suspends_minor(client, db_session, active_event, workflow_calls):
    from app.services.participant_service import ParticipantService
    guardian, minor = await _linked_and_cleared(client, db_session, active_event)
    db_session.expunge_all()
    assert await ParticipantService(db_session).delete_participant(guardian.id)
    m = await _reload(db_session, User, minor.id)
    assert m.guardian_user_id is None
    assert not await minor_service.participant_is_cleared(db_session, m, active_event)


# ------------------------------------------------------------ in person

async def test_minor_in_person_needs_guardian_in_person(client, db_session, active_event, workflow_calls):
    guardian, minor = await _linked_and_cleared(client, db_session, active_event)
    m = await _reload(db_session, User, minor.id)
    m.password_hash = hash_password("pw-12345")
    db_session.add(ParticipantAction(user_id=minor.id, event_id=active_event.id,
                                     action_type="in_person_attendance", title="In person"))
    await db_session.commit()
    action_id = (await db_session.execute(
        select(ParticipantAction.id).where(ParticipantAction.user_id == minor.id))).scalar_one()

    await login(client, minor.email)
    resp = await client.post(f"/api/participants/actions/{action_id}/respond", json={"status": "confirmed"})
    assert resp.status_code == 400 and resp.json()["detail"] == minor_service.IN_PERSON_MESSAGE
    assert (await _reload(db_session, User, minor.id)).confirmed_in_person is False

    await _in_person(db_session, guardian, active_event)
    resp = await client.post(f"/api/participants/actions/{action_id}/respond", json={"status": "confirmed"})
    assert resp.status_code == 200, resp.text
    assert (await _reload(db_session, User, minor.id)).confirmed_in_person is True

    # Guardian withdraws from in person -> the minor's goes too
    g_action = (await db_session.execute(select(ParticipantAction).where(
        ParticipantAction.user_id == guardian.id))).scalar_one()
    g_action.status = "pending"
    await db_session.commit()
    await login(client, guardian.email)
    resp = await client.post(f"/api/participants/actions/{g_action.id}/respond", json={"status": "declined"})
    assert resp.status_code == 200
    assert (await _reload(db_session, User, minor.id)).confirmed_in_person is False


# ----------------------------------------------------------------- gating

GATED = [
    ("post", "/api/vpn/request", {"count": 1, "key_type": "cyber"}),
    ("get", "/api/vpn/my-config", None),
    ("get", "/api/vpn/my-config/download", None),
    ("get", "/api/vpn/my-configs/download", None),
    ("get", "/api/vpn/download-batch/abc", None),
    ("post", "/api/participants/instances", {"template_id": 1, "name": "x"}),
    ("post", "/api/tls/certificates", {"ca_chain_id": 1, "common_name": "x.example.org"}),
    ("get", "/api/tls/certificates/1/download", None),
]


@pytest.mark.parametrize("method,path,body", GATED)
async def test_gated_routes_forbidden_for_uncleared_minor(client, db_session, active_event, invitee_role,
                                                          method, path, body):
    minor = await make_user(db_session, "kid@example.org", "Kim", "Kid", role_id=invitee_role.id,
                            password_hash=hash_password("pw-12345"),
                            adult_on=date(TODAY.year + 1, TODAY.month, 1))
    db_session.add(EventParticipation(user_id=minor.id, event_id=active_event.id, status="confirmed"))
    await db_session.commit()
    await login(client, minor.email)
    kwargs = {"json": body} if body is not None else {}
    resp = await getattr(client, method)(path, **kwargs)
    assert resp.status_code == 403, (path, resp.status_code, resp.text)
    assert "guardian" in resp.json()["detail"]


async def test_gated_route_open_to_adults(client, db_session, active_event, invitee_role):
    adult = await make_user(db_session, "adult@example.org", role_id=invitee_role.id,
                            password_hash=hash_password("pw-12345"))
    await login(client, adult.email)
    resp = await client.get("/api/vpn/my-config")
    assert resp.status_code != 403


async def test_cpe_ineligible_without_consent(db_session, active_event):
    from app.services.cpe_certificate_service import CPECertificateService
    active_event.start_date = TODAY - timedelta(days=3)
    active_event.end_date = TODAY - timedelta(days=1)
    minor = await make_user(db_session, "kid@example.org", adult_on=date(TODAY.year + 1, TODAY.month, 1))
    adult = await make_user(db_session, "adult@example.org")
    await db_session.commit()
    svc = CPECertificateService(db_session)
    minor_result = await svc.check_eligibility(minor.id, active_event)
    assert minor_result["eligible"] is False and minor_result["criteria"]["guardian_consent"] is False
    adult_result = await svc.check_eligibility(adult.id, active_event)
    assert "guardian_consent" not in adult_result["criteria"]


# ------------------------------------------------------------------ emails

async def test_guardian_copied_on_essential_email_not_optional(db_session):
    from app.services.email_queue_service import EmailQueueService
    guardian = await make_user(db_session, "parent@example.org")
    minor = await make_user(db_session, "kid@example.org", guardian_user_id=guardian.id,
                            guardian_link_status="confirmed",
                            adult_on=date(TODAY.year + 1, TODAY.month, 1))
    q = EmailQueueService(db_session)
    await q.enqueue_email(user_id=minor.id, template_name="logistics", custom_vars={"x": 1})
    await q.enqueue_email(user_id=minor.id, template_name="announce",
                          custom_vars={"future_contact_withdraw_url": "u"})
    rows = (await db_session.execute(select(EmailQueue))).scalars().all()
    logistics = sorted(r.recipient_email for r in rows if r.template_name == "logistics")
    assert logistics == ["kid@example.org", "parent@example.org"]
    assert [r.recipient_email for r in rows if r.template_name == "announce"] == ["kid@example.org"]
    copy = next(r for r in rows if r.recipient_email == "parent@example.org")
    assert copy.custom_vars["__recipient_email"] == "parent@example.org"
    # Duplicate protection still works with the copy present
    again = await q.enqueue_email(user_id=minor.id, template_name="logistics", custom_vars={"x": 1})
    assert again.recipient_email == "kid@example.org"
    assert await count(db_session, EmailQueue) == 3


async def test_optional_email_needs_guardian_agreement(db_session, active_event):
    guardian = await make_user(db_session, "parent@example.org")
    minor = await make_user(db_session, "kid@example.org", guardian_user_id=guardian.id,
                            future_contact_consent=True,
                            adult_on=date(TODAY.year + 1, TODAY.month, 1))
    assert not await minor_service.optional_email_allowed(db_session, minor)
    db_session.add(GuardianConsent(minor_user_id=minor.id, guardian_user_id=guardian.id,
                                   event_id=active_event.id, relationship_type="parent",
                                   guardian_name_typed="Pat Parent", consent_text_version="v1",
                                   optional_email_consent=True))
    await db_session.commit()
    assert await minor_service.optional_email_allowed(db_session, minor)


# ------------------------------------------------------- audit + turning 18

async def test_audit_entries_hold_ids_only(client, db_session, active_event, workflow_calls):
    guardian, minor = await _linked_and_cleared(client, db_session, active_event)
    await client.post(f"/api/guardian/minors/{minor.id}/withdraw")
    entries = (await db_session.execute(select(AuditLog).where(
        AuditLog.action.in_(("GUARDIAN_CONSENT_GIVEN", "GUARDIAN_CONSENT_WITHDRAWN",
                             "MINOR_ACCESS_SUSPENDED"))))).scalars().all()
    assert {e.action for e in entries} == {"GUARDIAN_CONSENT_GIVEN", "GUARDIAN_CONSENT_WITHDRAWN",
                                           "MINOR_ACCESS_SUSPENDED"}
    for e in entries:
        text = str(e.details).lower()
        for identity in ("kid@example.org", "parent@example.org", "kim", "pat parent"):
            assert identity not in text


async def test_turning_18_clears_birth_month(db_session, test_settings):
    from app.services.retention_service import RetentionService
    grown = await make_user(db_session, "grown@example.org", birth_year_month=date(2008, 1, 1),
                            adult_on=date(2026, 1, 1))
    young = await make_user(db_session, "young@example.org", birth_year_month=date(2010, 1, 1),
                            adult_on=date(2028, 1, 1))
    result = await RetentionService(db_session, settings=test_settings).minor_housekeeping(False)
    assert result["turned_18"] == 1
    assert (await _reload(db_session, User, grown.id)).birth_year_month is None
    assert (await _reload(db_session, User, grown.id)).adult_on == date(2026, 1, 1)
    assert (await _reload(db_session, User, young.id)).birth_year_month == date(2010, 1, 1)


def test_age_brackets_month_granularity():
    bym = date(2010, 6, 1)
    assert minor_service.age_bracket(bym, date(2026, 5, 31)) == "under_16"
    assert minor_service.age_bracket(bym, date(2026, 6, 1)) == "minor"
    assert minor_service.age_bracket(bym, date(2028, 6, 1)) == "adult"
