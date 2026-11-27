"""Privacy choices on the confirm page, do-not-invite list, consent withdrawal,
and admin privacy tools. Assert DB state, not just status codes."""
import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.invite_suppression import InviteSuppression
from app.models.user import User
from app.services.consent_service import make_withdraw_token
from app.services.invite_suppression_service import SUPPRESSED_MESSAGE, email_hmac
from tests.personal_data_seed import make_user

pytestmark = pytest.mark.asyncio


async def _invited(db, email="pat@example.org", **kw):
    return await make_user(db, email, "Pat", "Invitee", confirmation_code=f"code-{email}", **kw)


async def _reload(db, user_id):
    db.expunge_all()
    return await db.get(User, user_id)


# ------------------------------------------------------------------ accept

async def test_accept_requires_age_statement(client, db_session, active_event):
    user = await _invited(db_session)
    resp = await client.post("/api/public/confirm/accept", json={
        "confirmation_code": user.confirmation_code, "terms_accepted": True, "terms_version": "1.0",
    })
    assert resp.status_code == 400
    assert (await _reload(db_session, user.id)).confirmed == "UNKNOWN"


@pytest.mark.parametrize("ticked", [True, False])
async def test_accept_records_age_and_consent(client, db_session, active_event, ticked):
    user = await _invited(db_session)
    resp = await client.post("/api/public/confirm/accept", json={
        "confirmation_code": user.confirmation_code, "terms_accepted": True, "terms_version": "1.0",
        "age_attested": True, "future_contact_consent": ticked,
    })
    assert resp.status_code == 200, resp.text
    u = await _reload(db_session, user.id)
    assert u.confirmed == "YES"
    assert u.age_attested_at is not None and u.age_attestation
    assert u.future_contact_consent is ticked and u.future_contact_consent_at is not None


# ----------------------------------------------------------------- decline

@pytest.mark.parametrize("choice,consent,suppressed", [
    (None, False, False),                 # default = just not this time
    ("not_this_time", False, False),
    ("future_events", True, False),
    ("do_not_invite", False, True),
])
async def test_decline_choices(client, db_session, active_event, choice, consent, suppressed):
    user = await _invited(db_session)
    body = {"confirmation_code": user.confirmation_code, "reason": "busy"}
    if choice:
        body["future_contact_choice"] = choice
    resp = await client.post("/api/public/confirm/decline", json=body)
    assert resp.status_code == 200, resp.text

    u = await _reload(db_session, user.id)
    assert u.confirmed == "NO"
    assert u.future_contact_consent is consent
    rows = (await db_session.execute(select(InviteSuppression))).scalars().all()
    assert [r.email_hmac for r in rows] == ([email_hmac(user.email)] if suppressed else [])


async def test_decline_rejects_unknown_choice(client, db_session, active_event):
    user = await _invited(db_session)
    resp = await client.post("/api/public/confirm/decline", json={
        "confirmation_code": user.confirmation_code, "future_contact_choice": "spam me",
    })
    assert resp.status_code == 400


# --------------------------------------------------------- do-not-invite list

def test_hmac_stable_across_normalization():
    assert email_hmac("  First.Last@GMAIL.com ") == email_hmac("firstlast@gmail.com")
    assert email_hmac("a@example.org") != email_hmac("b@example.org")
    assert len(email_hmac("a@example.org")) == 64


async def _suppress(db, email):
    db.add(InviteSuppression(email_hmac=email_hmac(email)))
    await db.commit()


async def test_suppression_blocks_admin_creation(authenticated_admin_client, db_session):
    await _suppress(db_session, "blocked@example.org")
    resp = await authenticated_admin_client.post("/api/admin/participants", json={
        "email": "Blocked@Example.org", "first_name": "B", "last_name": "L", "country": "USA",
    })
    assert resp.status_code == 409
    assert resp.json()["detail"] == SUPPRESSED_MESSAGE
    assert (await db_session.execute(
        select(User).where(User.email_normalized == "blocked@example.org")
    )).scalar_one_or_none() is None


async def test_suppression_blocks_referrer_creation(authenticated_sponsor_client, db_session):
    await _suppress(db_session, "blocked@example.org")
    resp = await authenticated_sponsor_client.post("/api/sponsors/my-invitees", json={
        "email": "blocked@example.org", "first_name": "B", "last_name": "L", "country": "USA",
    })
    assert resp.status_code == 409
    assert resp.json()["detail"] == SUPPRESSED_MESSAGE


async def test_admin_can_add_and_remove_suppression(authenticated_admin_client, db_session):
    add = await authenticated_admin_client.post("/api/admin/invite-suppressions",
                                                json={"email": "x@example.org"})
    assert add.status_code == 200 and add.json()["added"] is True
    check = await authenticated_admin_client.post("/api/admin/invite-suppressions/check",
                                                  json={"email": "X@example.org"})
    assert check.json()["suppressed"] is True
    rm = await authenticated_admin_client.post("/api/admin/invite-suppressions/remove",
                                               json={"email": "x@example.org"})
    assert rm.json()["removed"] is True
    assert (await db_session.execute(select(InviteSuppression))).first() is None
    logs = (await db_session.execute(
        select(AuditLog).where(AuditLog.action.like("INVITE_SUPPRESSION_%"))
    )).scalars().all()
    assert len(logs) == 2 and all("x@example.org" not in str(log.details) for log in logs)


# --------------------------------------------------------- consent withdrawal

async def test_opening_withdraw_link_only_asks(client, db_session):
    """A GET (what email scanners and link previews do) changes nothing."""
    user = await make_user(db_session, "fan@example.org", future_contact_consent=True)
    token = make_withdraw_token(user.id)
    resp = await client.get(f"/future-contact/withdraw?token={token}")
    assert resp.status_code == 200
    assert "Stop these emails" in resp.text and f'value="{token}"' in resp.text
    assert (await _reload(db_session, user.id)).future_contact_consent is True


async def test_confirm_button_withdraws(client, db_session):
    user = await make_user(db_session, "fan@example.org", future_contact_consent=True)
    resp = await client.post("/future-contact/withdraw", data={"token": make_withdraw_token(user.id)})
    assert resp.status_code == 200 and "Done." in resp.text
    assert (await _reload(db_session, user.id)).future_contact_consent is False
    entries = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "PRIVACY_CHOICES_RECORDED")
    )).scalars().all()
    assert [e.details["source"] for e in entries] == ["withdraw_link"]


async def test_mail_client_one_click_post_withdraws(client, db_session):
    """RFC 8058: the client POSTs 'List-Unsubscribe=One-Click' to the URL (token in the query)."""
    user = await make_user(db_session, "fan@example.org", future_contact_consent=True)
    resp = await client.post(
        f"/future-contact/withdraw?token={make_withdraw_token(user.id)}",
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert (await _reload(db_session, user.id)).future_contact_consent is False


async def test_withdraw_rejects_forged_token(client, db_session):
    user = await make_user(db_session, "fan@example.org", future_contact_consent=True)
    forged = f"eyJ1Ijo{user.id}fQ.forged"
    assert (await client.get(f"/future-contact/withdraw?token={forged}")).status_code == 400
    assert (await client.post("/future-contact/withdraw", data={"token": forged})).status_code == 400
    assert (await _reload(db_session, user.id)).future_contact_consent is True


async def test_withdraw_page_when_already_off(client, db_session):
    user = await make_user(db_session, "fan@example.org", future_contact_consent=False)
    resp = await client.get(f"/future-contact/withdraw?token={make_withdraw_token(user.id)}")
    assert resp.status_code == 200
    assert "Stop these emails" not in resp.text and "You're not receiving" in resp.text


def test_withdraw_post_is_csrf_exempt():
    """Mail clients' one-click POST carries no CSRF cookie; the signed token authorizes it.
    (The test client disables CSRF entirely, so check the exemption list itself.)"""
    from app.main import csrf_exempt_urls
    assert "/future-contact/withdraw" in csrf_exempt_urls


async def test_profile_privacy_toggle(authenticated_invitee_client, db_session, invitee_user):
    resp = await authenticated_invitee_client.put("/api/user/privacy",
                                                  json={"future_contact_consent": True})
    assert resp.status_code == 200
    assert (await _reload(db_session, invitee_user.id)).future_contact_consent is True
    got = await authenticated_invitee_client.get("/api/user/privacy")
    assert got.json()["future_contact_consent"] is True


# ------------------------------------------------------------- admin tools

@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/admin/retention/dry-run", None),
    ("get", "/api/admin/retention/status", None),
    ("post", "/api/admin/invite-suppressions", {"email": "x@example.org"}),
    ("post", "/api/admin/invite-suppressions/remove", {"email": "x@example.org"}),
    ("post", "/api/admin/participants/1/delete-data", {"confirm_email": "x@example.org"}),
    ("put", "/api/admin/participants/1/retention-hold", {"until": None}),
])
async def test_admin_privacy_routes_forbidden_for_referrers(authenticated_sponsor_client, method,
                                                            path, body):
    kwargs = {"json": body} if body is not None else {}
    resp = await getattr(authenticated_sponsor_client, method)(path, **kwargs)
    assert resp.status_code == 403


async def test_delete_data_requires_typed_email(authenticated_admin_client, db_session):
    target = await make_user(db_session, "req@example.org")
    wrong = await authenticated_admin_client.post(
        f"/api/admin/participants/{target.id}/delete-data", json={"confirm_email": "nope@example.org"})
    assert wrong.status_code == 400
    assert target.id in set((await db_session.execute(select(User.id))).scalars().all())

    ok = await authenticated_admin_client.post(
        f"/api/admin/participants/{target.id}/delete-data", json={"confirm_email": "REQ@example.org"})
    assert ok.status_code == 200
    db_session.expunge_all()
    assert await db_session.get(User, target.id) is None
    entry = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "DATA_DELETION_REQUEST")
    )).scalar_one()
    assert entry.details == {"target_user_id": target.id}


async def test_retention_hold_and_dry_run(authenticated_admin_client, db_session):
    target = await make_user(db_session, "keep@example.org")
    resp = await authenticated_admin_client.put(
        f"/api/admin/participants/{target.id}/retention-hold", json={"until": "2030-01-01T00:00:00Z"})
    assert resp.status_code == 200
    assert (await _reload(db_session, target.id)).retention_hold_until is not None

    dry = await authenticated_admin_client.post("/api/admin/retention/dry-run")
    assert dry.status_code == 200 and dry.json()["dry_run"] is True
    status = await authenticated_admin_client.get("/api/admin/retention/status")
    assert status.json()["last_run"]["results"]["trigger"] == "manual"
    assert status.json()["settings"]["enabled"] is False
