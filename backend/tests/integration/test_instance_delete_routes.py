"""Instance delete routes: unconfirmed deletes fail loudly, force is admin-only.

Asserts database state as well as status codes, because these routes commit
before building their response.
"""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.instance import Instance
from app.models.redirector import Redirector, RedirectorStatus
from app.services.digitalocean_service import DigitalOceanService


pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _real_external_calls(monkeypatch):
    monkeypatch.delenv("STAGING_STUB_EXTERNALS", raising=False)


def _provider_returns(value):
    return patch.object(DigitalOceanService, "delete_instance", new=AsyncMock(return_value=value))


@pytest.fixture
async def instance(db_session, admin_user):
    inst = Instance(
        name="cs-box",
        image_id="ubuntu-22",
        provider="digitalocean",
        provider_instance_id="droplet-1",
        status="ACTIVE",
        created_by_user_id=admin_user.id,
    )
    db_session.add(inst)
    await db_session.commit()
    return inst


@pytest.fixture
async def linked_redirector(db_session, instance, admin_user):
    redir = Redirector(
        name="platform-redir",
        current_ip="10.0.0.5",
        ssh_username="root",
        instance_id=instance.id,
        owner_id=admin_user.id,
        status=RedirectorStatus.ONLINE.value,
    )
    db_session.add(redir)
    await db_session.commit()
    return redir


async def _status(db_session, model, row_id):
    db_session.expire_all()
    return (await db_session.execute(select(model.status).where(model.id == row_id))).scalar_one()


@pytest.mark.asyncio
class TestAdminDeleteRoute:

    async def test_unconfirmed_delete_returns_502_and_keeps_row(
        self, authenticated_admin_client, db_session, instance
    ):
        with _provider_returns(False):
            response = await authenticated_admin_client.delete(f"/api/instances/{instance.id}")

        assert response.status_code == 502
        assert "droplet-1" not in response.text  # no provider details leaked
        assert await _status(db_session, Instance, instance.id) == "ACTIVE"

    async def test_unconfirmed_delete_does_not_isolate_redirector(
        self, authenticated_admin_client, db_session, instance, linked_redirector
    ):
        with _provider_returns(False):
            response = await authenticated_admin_client.delete(f"/api/instances/{instance.id}")

        assert response.status_code == 502
        assert await _status(db_session, Redirector, linked_redirector.id) == RedirectorStatus.ONLINE.value

    async def test_confirmed_delete_isolates_redirector(
        self, authenticated_admin_client, db_session, instance, linked_redirector
    ):
        with _provider_returns(True):
            response = await authenticated_admin_client.delete(f"/api/instances/{instance.id}")

        assert response.status_code == 200
        assert await _status(db_session, Instance, instance.id) == "DELETED"
        assert await _status(db_session, Redirector, linked_redirector.id) == RedirectorStatus.ISOLATED.value

    async def test_admin_force_deletes_unconfirmed_instance(
        self, authenticated_admin_client, db_session, instance
    ):
        with _provider_returns(False):
            response = await authenticated_admin_client.delete(
                f"/api/instances/{instance.id}", params={"force": "true"}
            )

        assert response.status_code == 200
        assert await _status(db_session, Instance, instance.id) == "DELETED"


@pytest.mark.asyncio
class TestForceIsAdminOnly:

    async def test_invitee_cannot_force(
        self, authenticated_invitee_client, db_session, instance
    ):
        provider = AsyncMock(return_value=False)
        with patch.object(DigitalOceanService, "delete_instance", new=provider):
            response = await authenticated_invitee_client.delete(
                f"/api/instances/{instance.id}", params={"force": "true"}
            )

        assert response.status_code == 403
        provider.assert_not_awaited()
        assert await _status(db_session, Instance, instance.id) == "ACTIVE"
