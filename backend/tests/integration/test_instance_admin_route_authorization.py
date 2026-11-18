"""Admin instance routes are admin-only; participant self-service is unchanged.

Participant roles hold instances.provision and instances.delete for the
self-service routes under /api/participants. The admin routes under
/api/instances must additionally require instances.view_all.

Asserts provider calls and database state, not just status codes.
"""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.models.instance import Instance
from app.services.digitalocean_service import DigitalOceanService
from app.services.instance_service import InstanceService
from app.services.openstack_service import OpenStackService


pytestmark = [pytest.mark.integration]

NON_ADMINS = ["invitee", "sponsor"]


@pytest.fixture(autouse=True)
def _real_external_calls(monkeypatch):
    monkeypatch.delenv("STAGING_STUB_EXTERNALS", raising=False)


@pytest.fixture
def as_actor(client, sponsor_session_token, invitee_session_token, admin_session_token):
    """Authenticate the shared client as a named actor at call time."""
    tokens = {
        "sponsor": sponsor_session_token,
        "invitee": invitee_session_token,
        "admin": admin_session_token,
    }

    def _login_as(actor: str):
        client.cookies.set("session_token", tokens[actor])
        return client

    return _login_as


def _instance(owner, name="target", provider_id="droplet-1"):
    return Instance(
        name=name,
        image_id="ubuntu-22",
        provider="digitalocean",
        provider_instance_id=provider_id,
        status="ACTIVE",
        created_by_user_id=owner.id,
    )


@pytest.fixture
async def admin_instance(db_session, admin_user):
    inst = _instance(admin_user)
    db_session.add(inst)
    await db_session.commit()
    return inst


async def _status(db_session, instance_id):
    db_session.expire_all()
    return (
        await db_session.execute(select(Instance.status).where(Instance.id == instance_id))
    ).scalar_one()


async def _instance_count(db_session):
    return (await db_session.execute(select(func.count(Instance.id)))).scalar_one()


def _provider_delete(value=True):
    return patch.object(
        DigitalOceanService, "delete_instance", new=AsyncMock(return_value=value)
    )


@pytest.mark.asyncio
class TestNonAdminsBlockedFromAdminRoutes:

    @pytest.mark.parametrize("actor", NON_ADMINS)
    async def test_delete_any_instance(self, actor, as_actor, db_session, admin_instance):
        with _provider_delete() as provider:
            response = await as_actor(actor).delete(f"/api/instances/{admin_instance.id}")

        assert response.status_code == 403
        provider.assert_not_awaited()
        assert await _status(db_session, admin_instance.id) == "ACTIVE"

    @pytest.mark.parametrize("actor", NON_ADMINS)
    async def test_bulk_delete(self, actor, as_actor, db_session, admin_instance):
        with _provider_delete() as provider:
            response = await as_actor(actor).post(
                "/api/instances/bulk-delete", json={"instance_ids": [admin_instance.id]}
            )

        assert response.status_code == 403
        provider.assert_not_awaited()
        assert await _status(db_session, admin_instance.id) == "ACTIVE"

    @pytest.mark.parametrize("actor", NON_ADMINS)
    async def test_create_arbitrary_instance(self, actor, as_actor, db_session):
        before = await _instance_count(db_session)
        with patch.object(
            InstanceService, "create_and_track_instance", new=AsyncMock()
        ) as create:
            response = await as_actor(actor).post(
                "/api/instances",
                json={
                    "name": "big-box",
                    "provider": "digitalocean",
                    "size_slug": "s-32vcpu-64gb",
                    "region": "nyc1",
                    "image_id": "ubuntu-22-04-x64",
                },
            )

        assert response.status_code == 403
        create.assert_not_awaited()
        assert await _instance_count(db_session) == before

    @pytest.mark.parametrize("actor", NON_ADMINS)
    async def test_bulk_create(self, actor, as_actor, db_session):
        before = await _instance_count(db_session)
        with patch.object(
            OpenStackService, "bulk_create_instances", new=AsyncMock(return_value=(50, []))
        ) as bulk:
            response = await as_actor(actor).post(
                "/api/instances/bulk",
                json={"name_prefix": "x", "count": 50, "flavor_id": "f", "image_id": "i",
                      "network_id": "n"},
            )

        assert response.status_code == 403
        bulk.assert_not_awaited()
        assert await _instance_count(db_session) == before

    @pytest.mark.parametrize("actor", NON_ADMINS)
    async def test_redirector_status(self, actor, as_actor, admin_instance):
        response = await as_actor(actor).get(
            f"/api/instances/{admin_instance.id}/redirector-status"
        )
        assert response.status_code == 403


@pytest.mark.asyncio
class TestAdminStillAllowed:

    async def test_admin_delete(self, as_actor, db_session, admin_instance):
        with _provider_delete() as provider:
            response = await as_actor("admin").delete(f"/api/instances/{admin_instance.id}")

        assert response.status_code == 200, response.text
        provider.assert_awaited_once()
        assert await _status(db_session, admin_instance.id) == "DELETED"

    async def test_admin_bulk_delete(self, as_actor, db_session, admin_instance):
        with _provider_delete():
            response = await as_actor("admin").post(
                "/api/instances/bulk-delete", json={"instance_ids": [admin_instance.id]}
            )

        assert response.status_code == 200, response.text
        assert response.json()["success_count"] == 1
        assert await _status(db_session, admin_instance.id) == "DELETED"

    async def test_admin_create_reaches_service(self, as_actor, db_session, admin_user):
        created = _instance(admin_user, name="admin-box", provider_id="droplet-2")
        db_session.add(created)
        await db_session.commit()
        with patch.object(
            InstanceService, "create_and_track_instance", new=AsyncMock(return_value=created)
        ) as create:
            response = await as_actor("admin").post(
                "/api/instances",
                json={"name": "admin-box", "provider": "digitalocean"},
            )

        assert response.status_code == 201, response.text
        create.assert_awaited_once()

    async def test_admin_bulk_create_reaches_service(self, as_actor):
        with patch.object(
            OpenStackService, "bulk_create_instances", new=AsyncMock(return_value=(2, []))
        ) as bulk:
            response = await as_actor("admin").post(
                "/api/instances/bulk",
                json={"name_prefix": "x", "count": 2, "flavor_id": "f", "image_id": "i",
                      "network_id": "n"},
            )

        assert response.status_code == 201, response.text
        bulk.assert_awaited_once()

    async def test_admin_redirector_status(self, as_actor, admin_instance):
        response = await as_actor("admin").get(
            f"/api/instances/{admin_instance.id}/redirector-status"
        )
        assert response.status_code == 200
        assert response.json() == {"under_management": False}


@pytest.mark.asyncio
class TestParticipantSelfServiceUnchanged:

    async def test_invitee_can_delete_own_instance(
        self, as_actor, db_session, invitee_user
    ):
        own = _instance(invitee_user, name="mine", provider_id="droplet-3")
        db_session.add(own)
        await db_session.commit()

        with _provider_delete() as provider:
            response = await as_actor("invitee").delete(
                f"/api/participants/instances/{own.id}"
            )

        assert response.status_code == 200, response.text
        provider.assert_awaited_once()
        assert await _status(db_session, own.id) == "DELETED"

    async def test_invitee_still_cannot_delete_others_via_self_service(
        self, as_actor, db_session, admin_instance
    ):
        with _provider_delete() as provider:
            response = await as_actor("invitee").delete(
                f"/api/participants/instances/{admin_instance.id}"
            )

        assert response.status_code == 403
        provider.assert_not_awaited()
        assert await _status(db_session, admin_instance.id) == "ACTIVE"
