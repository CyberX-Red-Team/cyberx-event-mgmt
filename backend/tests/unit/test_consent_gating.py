"""Future-contact consent: who gets automatic next-event invitations and
optional emails (announcements), and the privacy links in invitations."""
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.email_queue import EmailQueue
from app.models.event import EventParticipation
from app.services import consent_service
from app.services.consent_service import auto_invite_allowed, may_receive_optional_email
from app.services.email_service import (
    PRIVACY_FOOTER_FLAG, append_privacy_footer, privacy_email_vars,
)
from tests.personal_data_seed import make_event, make_user

pytestmark = pytest.mark.asyncio


def person(role="invitee", consent=None):
    return SimpleNamespace(role=role, future_contact_consent=consent, id=7)


@pytest.mark.parametrize("p,prior,legacy,expected", [
    (person(consent=True), True, False, True),        # asked for invitations
    (person(consent=False), True, True, False),       # chose not to (even in transition)
    (person(consent=None), False, False, True),       # new referral, first invitation
    (person(consent=None), True, True, True),         # predates consent, 2027 transition on
    (person(consent=None), True, False, False),       # predates consent, transition off
    (person(role="sponsor", consent=False), True, False, True),  # staff exempt
    (person(role="admin", consent=None), True, False, True),
])
def test_auto_invite_allowed(monkeypatch, p, prior, legacy, expected):
    monkeypatch.setattr(consent_service, "get_settings",
                        lambda: SimpleNamespace(LEGACY_FUTURE_INVITES_ENABLED=legacy))
    assert auto_invite_allowed(p, prior) is expected


def test_optional_email_needs_consent_or_staff():
    assert may_receive_optional_email(person(consent=True))
    assert not may_receive_optional_email(person(consent=None))
    assert not may_receive_optional_email(person(consent=False))
    assert may_receive_optional_email(person(role="sponsor"))


async def test_event_activation_skips_people_who_declined_future_contact(db_session, monkeypatch,
                                                                        test_settings):
    """Automatic invitations: consented + new referrals + (transition) legacy; never 'no'."""
    from app.tasks import invitation_emails

    past = await make_event(db_session, "Last Year", is_archived=True)
    current = await make_event(db_session, "This Year", is_active=True, registration_open=True)
    yes = await make_user(db_session, "yes@example.org", future_contact_consent=True)
    no = await make_user(db_session, "no@example.org", future_contact_consent=False)
    legacy = await make_user(db_session, "legacy@example.org")
    new_referral = await make_user(db_session, "new@example.org")
    for u in (yes, no, legacy):
        db_session.add(EventParticipation(user_id=u.id, event_id=past.id, status="declined"))
    await db_session.commit()

    @asynccontextmanager
    async def fake_session():
        yield db_session

    monkeypatch.setattr(invitation_emails, "AsyncSessionLocal", fake_session)
    monkeypatch.setattr(consent_service, "get_settings",
                        lambda: test_settings.model_copy(update={"LEGACY_FUTURE_INVITES_ENABLED": False}))
    # Keep the real queueing, but don't depend on workflow rows existing.
    await invitation_emails.send_invitations_to_unknown_participants(current.id, current.name)

    invited = set((await db_session.execute(
        select(EventParticipation.user_id).where(EventParticipation.event_id == current.id)
    )).scalars().all())
    assert invited == {yes.id, new_referral.id}

    queued = (await db_session.execute(select(EmailQueue))).scalars().all()
    by_user = {q.user_id: q.custom_vars for q in queued}
    assert by_user[yes.id]["future_contact_withdraw_url"]
    assert "future_contact_withdraw_url" not in by_user[new_referral.id]
    assert all(v["privacy_policy_url"] == "https://cyberxredteam.org/privacy" for v in by_user.values())
    assert no.id not in by_user and legacy.id not in by_user


def test_privacy_vars_and_footer():
    consented = SimpleNamespace(id=3, future_contact_consent=True)
    plain = SimpleNamespace(id=4, future_contact_consent=None)
    v = privacy_email_vars(consented)
    assert v[PRIVACY_FOOTER_FLAG] is True and "future-contact/withdraw?token=" in v["future_contact_withdraw_url"]
    assert "future_contact_withdraw_url" not in privacy_email_vars(plain)

    html, text = append_privacy_footer("<html><body><p>Hi</p></body></html>", "Hi", v)
    assert "https://cyberxredteam.org/privacy" in html and html.index("privacy") < html.index("</body>")
    assert "Stop future invitations" in html and v["future_contact_withdraw_url"] in text

    # Templates that already link the policy aren't changed
    already = '<p><a href="https://cyberxredteam.org/privacy">Privacy</a></p>'
    assert append_privacy_footer(already, "", {"privacy_policy_url": "https://cyberxredteam.org/privacy"})[0] == already


async def test_bulk_optional_email_skips_people_without_consent(authenticated_admin_client, db_session,
                                                               monkeypatch):
    from app.models.email_template import EmailTemplate
    from app.services.email_service import EmailService

    tmpl = EmailTemplate(name="announcement", display_name="A", subject="S",
                         html_content="<body>x</body>", is_active=True)
    db_session.add(tmpl)
    yes = await make_user(db_session, "yes@example.org", future_contact_consent=True)
    no = await make_user(db_session, "no@example.org", future_contact_consent=False)
    await db_session.commit()

    sent_to = []

    async def fake_send(self, user, template, custom_subject=None, custom_vars=None, **kw):
        sent_to.append((user.id, dict(custom_vars or {})))
        return True, "ok", "id"

    monkeypatch.setattr(EmailService, "_send_email_with_template", fake_send)
    resp = await authenticated_admin_client.post("/api/email/bulk", json={
        "participant_ids": [yes.id, no.id], "template_id": tmpl.id, "optional_email": True,
    })
    assert resp.status_code == 200, resp.text
    assert [uid for uid, _ in sent_to] == [yes.id]
    assert sent_to[0][1]["future_contact_withdraw_url"]
    assert "1 skipped" in resp.json()["message"]
