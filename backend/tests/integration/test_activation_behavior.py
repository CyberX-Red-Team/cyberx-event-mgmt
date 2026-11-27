"""Characterization of what accepting an invitation activates for an adult.

Written before moving activation into ParticipantService.activate_participation()
so the refactor can be checked against unchanged adult behavior.
"""
import pytest
from sqlalchemy import select

from app.models.event import EventParticipation
from app.models.password_sync_queue import PasswordSyncQueue
from app.models.user import User
from app.services.workflow_service import WorkflowService
from app.utils.security import hash_password
from tests.personal_data_seed import make_user

pytestmark = pytest.mark.asyncio


@pytest.fixture
def workflow_calls(monkeypatch):
    calls = []

    async def fake_trigger(self, trigger_event, user_id, custom_vars=None, force=False):
        calls.append({"event": str(trigger_event), "user_id": user_id,
                      "vars": dict(custom_vars or {}), "force": force})
        return 1

    monkeypatch.setattr(WorkflowService, "trigger_workflow", fake_trigger)
    return calls


async def _accept(client, code):
    return await client.post("/api/public/confirm/accept", json={
        "confirmation_code": code, "terms_accepted": True, "terms_version": "1.0",
        "age_attested": True,
    })


async def test_invitee_accept_activates(client, db_session, active_event, workflow_calls):
    user = await make_user(db_session, "ada@example.org", "Ada", "Lovelace",
                           confirmation_code="c-ada")
    db_session.add(EventParticipation(user_id=user.id, event_id=active_event.id, status="invited"))
    await db_session.commit()

    resp = await _accept(client, "c-ada")
    assert resp.status_code == 200, resp.text

    db_session.expunge_all()
    u = await db_session.get(User, user.id)
    assert u.confirmed == "YES" and u.terms_accepted
    assert u.pandas_username == "alovelace"
    assert u.password_hash and u.pandas_password and u.password_phonetic
    assert u.keycloak_synced is False
    ep = (await db_session.execute(select(EventParticipation))).scalar_one()
    assert ep.status == "confirmed" and ep.confirmed_at and ep.terms_version_accepted == "1.0"
    sync = (await db_session.execute(select(PasswordSyncQueue))).scalars().all()
    assert [(s.operation, s.username) for s in sync] == [("create_user", "alovelace")]
    assert len(workflow_calls) == 1
    call = workflow_calls[0]
    assert call["event"].endswith("user_confirmed") and call["force"] is True
    assert call["vars"]["pandas_username"] == "alovelace"
    assert call["vars"]["pandas_password"] == u.pandas_password
    assert call["vars"]["event_name"] == active_event.name


async def test_sponsor_accept_keeps_password_and_sends_no_credentials(
        client, db_session, active_event, workflow_calls):
    user = await make_user(db_session, "sp@example.org", "Sam", "Sponsor", role="sponsor",
                           confirmation_code="c-sp", pandas_username="ssponsor",
                           password_hash=hash_password("keep-me"))
    user.pandas_password = "keep-me"
    await db_session.commit()

    resp = await _accept(client, "c-sp")
    assert resp.status_code == 200, resp.text

    db_session.expunge_all()
    u = await db_session.get(User, user.id)
    assert u.pandas_password == "keep-me"
    # Existing credentials not yet in Keycloak are queued for sync
    sync = (await db_session.execute(select(PasswordSyncQueue))).scalars().all()
    assert [(s.operation, s.username) for s in sync] == [("create_user", "ssponsor")]
    assert workflow_calls == []
