"""Guardian copies on emails sent directly (not through the queue), and the
removed API-only participation routes."""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.audit_log import EmailEvent
from app.models.email_template import EmailTemplate
from app.services.minor_service import guardian_for_copies
from tests.personal_data_seed import make_user

pytestmark = pytest.mark.asyncio

UNDER_18 = date(date.today().year + 1, date.today().month, 1)


@pytest.fixture
def sent(monkeypatch):
    """Record the To: address of every message handed to SendGrid."""
    out = []

    def fake_send(self, message):
        out.append(message.get()["personalizations"][0]["to"][0]["email"])
        return SimpleNamespace(status_code=202, headers={})

    monkeypatch.setattr("sendgrid.SendGridAPIClient.send", fake_send)
    return out


async def _family(db):
    guardian = await make_user(db, "parent@example.org", "Pat", "Parent")
    minor = await make_user(db, "kid@example.org", "Kim", "Kid", adult_on=UNDER_18,
                            guardian_user_id=guardian.id, guardian_link_status="confirmed")
    adult = await make_user(db, "adult@example.org", "Ada", "Adult")
    tmpl = EmailTemplate(name="logistics", display_name="L", subject="S",
                         html_content="<body>hi</body>", is_active=True)
    db.add(tmpl)
    await db.commit()
    return guardian, minor, adult, tmpl


async def test_bulk_template_send_copies_guardian(authenticated_admin_client, db_session, sent):
    guardian, minor, adult, tmpl = await _family(db_session)
    resp = await authenticated_admin_client.post("/api/email/bulk", json={
        "participant_ids": [minor.id, adult.id], "template_id": tmpl.id,
    })
    assert resp.status_code == 200, resp.text
    assert sorted(sent) == ["adult@example.org", "kid@example.org", "parent@example.org"]
    assert resp.json()["sent_count"] == 2  # copies aren't counted as recipients
    # The copy's record names the address it actually went to, under the minor's account
    events = (await db_session.execute(select(EmailEvent).where(EmailEvent.user_id == minor.id))).scalars().all()
    assert sorted(e.email_to for e in events) == ["kid@example.org", "parent@example.org"]


async def test_bulk_optional_email_not_copied(authenticated_admin_client, db_session, sent):
    from app.models.guardian_consent import GuardianConsent
    from tests.personal_data_seed import make_event
    guardian, minor, adult, tmpl = await _family(db_session)
    event = await make_event(db_session, "Ev")
    m = await db_session.get(type(minor), minor.id)
    m.future_contact_consent = True
    db_session.add(GuardianConsent(minor_user_id=minor.id, guardian_user_id=guardian.id, event_id=event.id,
                                   relationship_type="parent", guardian_name_typed="Pat Parent",
                                   consent_text_version="v1", optional_email_consent=True))
    await db_session.commit()
    resp = await authenticated_admin_client.post("/api/email/bulk", json={
        "participant_ids": [minor.id], "template_id": tmpl.id, "optional_email": True,
    })
    assert resp.status_code == 200, resp.text
    assert sent == ["kid@example.org"]


async def test_custom_send_copies_guardian_unless_optional(authenticated_admin_client, db_session, sent):
    guardian, minor, adult, tmpl = await _family(db_session)
    resp = await authenticated_admin_client.post("/api/email/send-custom", json={
        "participant_ids": [minor.id], "subject": "Schedule", "html_body": "<p>Doors at 18:00</p>",
    })
    assert resp.status_code == 200, resp.text
    assert sorted(sent) == ["kid@example.org", "parent@example.org"]


async def test_single_send_copies_guardian(authenticated_admin_client, db_session, sent):
    guardian, minor, adult, tmpl = await _family(db_session)
    resp = await authenticated_admin_client.post("/api/email/send", json={
        "participant_id": minor.id, "template_id": tmpl.id,
    })
    assert resp.status_code == 200, resp.text
    assert sorted(sent) == ["kid@example.org", "parent@example.org"]


async def test_adults_and_attachments_not_copied(db_session):
    guardian, minor, adult, tmpl = await _family(db_session)
    assert await guardian_for_copies(db_session, adult) is None
    assert (await guardian_for_copies(db_session, minor)).id == guardian.id
    # VPN configuration files are the participant's own access: never copied
    assert await guardian_for_copies(db_session, minor, has_attachment=True) is None
    assert await guardian_for_copies(db_session, minor, {"future_contact_withdraw_url": "u"}) is None


@pytest.mark.parametrize("method,path", [
    ("post", "/api/events/my/confirm"),
    ("post", "/api/events/my/decline?event_id=1"),
    ("post", "/api/events/1/invite"),
])
async def test_removed_participation_routes_stay_gone(authenticated_admin_client, method, path):
    """Participation changes only through the invitation link, which applies the
    age, consent and guardian rules."""
    resp = await getattr(authenticated_admin_client, method)(path, json={})
    assert resp.status_code in (404, 405)
