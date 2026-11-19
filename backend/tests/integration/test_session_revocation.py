"""Changing or clearing a user's login password ends their existing sessions.

Each test holds two real sessions (two logins = two devices), drives a real
route, then checks which session cookies still authenticate.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.session import Session
from app.models.user import User


pytestmark = [pytest.mark.integration]


async def _login(client, username, password):
    client.cookies.clear()
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.cookies.get("session_token")


async def _authenticates(client, token):
    client.cookies.clear()
    client.cookies.set("session_token", token)
    return (await client.get("/api/auth/me")).status_code == 200


def _as(client, token):
    client.cookies.clear()
    client.cookies.set("session_token", token)
    return client


async def _active_sessions(db_session, user_id):
    db_session.expire_all()
    return (await db_session.execute(
        select(Session).where(Session.user_id == user_id, Session.is_active == True)  # noqa: E712
    )).scalars().all()


@pytest.fixture
async def invitee_two_devices(client, invitee_user):
    first = await _login(client, invitee_user.email, "invitee123")
    second = await _login(client, invitee_user.email, "invitee123")
    assert first != second
    return first, second


@pytest.mark.asyncio
class TestPasswordChangesEndSessions:

    async def test_self_service_change_keeps_this_device_ends_others(
        self, client, db_session, invitee_user, invitee_two_devices,
    ):
        this_device, other_device = invitee_two_devices
        response = await _as(client, this_device).post(
            "/api/auth/password/change",
            json={"current_password": "invitee123", "new_password": "Brand-New-Pass-1"},
        )
        assert response.status_code == 200, response.text

        assert await _authenticates(client, this_device)
        assert not await _authenticates(client, other_device)
        # The change itself still works: new password logs in, old one doesn't.
        assert await _login(client, invitee_user.email, "Brand-New-Pass-1")
        client.cookies.clear()
        bad = await client.post(
            "/api/auth/login", json={"username": invitee_user.email, "password": "invitee123"},
        )
        assert bad.status_code == 401

    async def test_reset_by_token_ends_every_session(
        self, client, db_session, invitee_user, invitee_two_devices,
    ):
        # Reload: the harness clears the identity map before each request, so
        # the fixture's object is detached after the logins above.
        db_session.expire_all()
        user = (await db_session.execute(
            select(User).where(User.id == invitee_user.id)
        )).scalar_one()
        user.password_reset_token = "reset-token-123"
        user.password_reset_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        await db_session.commit()

        client.cookies.clear()
        response = await client.post(
            "/api/auth/password/reset/complete",
            json={"token": "reset-token-123", "new_password": "Reset-Pass-123"},
        )
        assert response.status_code == 200, response.text

        for token in invitee_two_devices:
            assert not await _authenticates(client, token)
        assert await _active_sessions(db_session, invitee_user.id) == []
        assert await _login(client, invitee_user.email, "Reset-Pass-123")

    async def test_admin_setting_a_password_ends_that_users_sessions_only(
        self, client, db_session, invitee_user, admin_user, invitee_two_devices,
    ):
        admin = await _login(client, admin_user.email, "admin123")
        response = await _as(client, admin).put(
            f"/api/admin/participants/{invitee_user.id}",
            json={"pandas_password": "Admin-Set-Pass-1"},
        )
        assert response.status_code == 200, response.text

        for token in invitee_two_devices:
            assert not await _authenticates(client, token)
        assert await _authenticates(client, admin)  # the admin's own session is untouched

    async def test_admin_update_without_password_keeps_sessions(
        self, client, db_session, invitee_user, admin_user, invitee_two_devices,
    ):
        admin = await _login(client, admin_user.email, "admin123")
        response = await _as(client, admin).put(
            f"/api/admin/participants/{invitee_user.id}", json={"first_name": "Renamed"},
        )
        assert response.status_code == 200, response.text

        for token in invitee_two_devices:
            assert await _authenticates(client, token)

    async def test_workflow_reset_clearing_credentials_ends_sessions(
        self, client, db_session, invitee_user, admin_user, invitee_two_devices,
    ):
        admin = await _login(client, admin_user.email, "admin123")
        response = await _as(client, admin).post(
            f"/api/admin/participants/{invitee_user.id}/reset-workflow"
            "?reset_credentials=true&reset_event_participation=false",
        )
        assert response.status_code == 200, response.text

        for token in invitee_two_devices:
            assert not await _authenticates(client, token)

    async def test_workflow_reset_keeping_credentials_keeps_sessions(
        self, client, db_session, invitee_user, admin_user, invitee_two_devices,
    ):
        admin = await _login(client, admin_user.email, "admin123")
        response = await _as(client, admin).post(
            f"/api/admin/participants/{invitee_user.id}/reset-workflow"
            "?reset_credentials=false&reset_event_participation=false",
        )
        assert response.status_code == 200, response.text

        for token in invitee_two_devices:
            assert await _authenticates(client, token)

    async def test_bulk_reset_ends_only_invitees_whose_credentials_were_cleared(
        self, client, db_session, invitee_user, sponsor_user, admin_user, invitee_two_devices,
    ):
        sponsor = await _login(client, sponsor_user.email, "sponsor123")
        admin = await _login(client, admin_user.email, "admin123")
        response = await _as(client, admin).post(
            "/api/admin/participants/bulk-reset-workflow"
            "?reset_credentials=true&reset_event_participation=false"
            f"&roles=invitee,sponsor&user_ids={invitee_user.id},{sponsor_user.id}",
        )
        assert response.status_code == 200, response.text

        for token in invitee_two_devices:
            assert not await _authenticates(client, token)
        assert await _authenticates(client, sponsor)   # sponsors keep credentials
        assert await _authenticates(client, admin)

    async def test_bulk_reset_keeping_credentials_keeps_sessions(
        self, client, db_session, invitee_user, admin_user, invitee_two_devices,
    ):
        admin = await _login(client, admin_user.email, "admin123")
        response = await _as(client, admin).post(
            "/api/admin/participants/bulk-reset-workflow"
            f"?reset_credentials=false&reset_event_participation=false&user_ids={invitee_user.id}",
        )
        assert response.status_code == 200, response.text

        for token in invitee_two_devices:
            assert await _authenticates(client, token)

    async def test_confirmation_issuing_new_credentials_ends_old_sessions(
        self, client, db_session, invitee_user, invitee_two_devices,
    ):
        db_session.expire_all()
        user = (await db_session.execute(
            select(User).where(User.id == invitee_user.id)
        )).scalar_one()
        user.confirmation_code = "confirm-code-123"
        user.confirmed = "UNKNOWN"
        await db_session.commit()

        client.cookies.clear()
        response = await client.post(
            "/api/public/confirm/accept",
            json={"confirmation_code": "confirm-code-123", "terms_accepted": True,
                  "terms_version": "1.0"},
        )
        assert response.status_code == 200, response.text

        for token in invitee_two_devices:
            assert not await _authenticates(client, token)
