"""Instance deletion must be confirmed by the provider before the row is dropped.

Previously delete_and_track_instance ignored the provider's result and soft-
deleted regardless, so a VM that failed to delete (bad credentials, rate limit,
outage) was marked DELETED and vanished from every view while still running.

Provider methods are patched with patch.object rather than mocking whole
classes, so the real factory and constructors still run.
"""
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.instance import Instance
from app.services.digitalocean_service import DigitalOceanService
from app.services.event_archive_service import EventArchiveService
from app.services.instance_service import InstanceDeletionError, InstanceService
from tests.unit.test_event_archive_service import _seed_archivable_event


@pytest.fixture(autouse=True)
def _real_external_calls(monkeypatch):
    """The stub flag would short-circuit the provider call these tests exercise."""
    monkeypatch.delenv("STAGING_STUB_EXTERNALS", raising=False)


async def _instance(db: AsyncSession, **kwargs) -> Instance:
    fields = dict(
        name="cs-box",
        image_id="ubuntu-22",
        provider="digitalocean",
        provider_instance_id="droplet-1",
        status="ACTIVE",
    )
    fields.update(kwargs)
    instance = Instance(**fields)
    db.add(instance)
    await db.commit()
    return instance


async def _reload(db: AsyncSession, instance_id: int) -> Instance:
    db.expire_all()
    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    return result.scalar_one()


def _provider_returns(value):
    return patch.object(DigitalOceanService, "delete_instance", new=AsyncMock(return_value=value))


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeleteAndTrackInstance:

    async def test_confirmed_delete_marks_row_deleted(self, db_session):
        instance = await _instance(db_session)

        with _provider_returns(True):
            ok = await InstanceService(db_session).delete_and_track_instance(instance.id)

        assert ok is True
        stored = await _reload(db_session, instance.id)
        assert stored.status == "DELETED"
        assert stored.deleted_at is not None

    async def test_already_gone_vm_404_is_treated_as_deleted(self, db_session):
        """A VM torn down by hand: the real DigitalOcean client gets a 404."""
        instance = await _instance(db_session)

        with patch.object(DigitalOceanService, "_check_configured", lambda self: None), \
             patch.object(httpx.AsyncClient, "delete",
                          new=AsyncMock(return_value=httpx.Response(404))):
            ok = await InstanceService(db_session).delete_and_track_instance(instance.id)

        assert ok is True
        assert (await _reload(db_session, instance.id)).status == "DELETED"

    async def test_unconfirmed_delete_leaves_row_in_place(self, db_session):
        instance = await _instance(db_session)

        with _provider_returns(False), pytest.raises(InstanceDeletionError) as exc:
            await InstanceService(db_session).delete_and_track_instance(instance.id)

        assert "did not confirm" in str(exc.value)
        stored = await _reload(db_session, instance.id)
        assert stored.status == "ACTIVE"
        assert stored.deleted_at is None

    async def test_real_provider_error_status_leaves_row_in_place(self, db_session):
        """End to end through the real client: a 401 is not a confirmation."""
        instance = await _instance(db_session)

        with patch.object(DigitalOceanService, "_check_configured", lambda self: None), \
             patch.object(httpx.AsyncClient, "delete",
                          new=AsyncMock(return_value=httpx.Response(401))), \
             pytest.raises(InstanceDeletionError):
            await InstanceService(db_session).delete_and_track_instance(instance.id)

        assert (await _reload(db_session, instance.id)).status == "ACTIVE"

    async def test_provider_exception_leaves_row_in_place(self, db_session):
        instance = await _instance(db_session)
        boom = AsyncMock(side_effect=RuntimeError("provider unreachable"))

        with patch.object(DigitalOceanService, "delete_instance", new=boom), \
             pytest.raises(InstanceDeletionError) as exc:
            await InstanceService(db_session).delete_and_track_instance(instance.id)

        assert "provider unreachable" in str(exc.value)
        assert isinstance(exc.value.__cause__, RuntimeError)
        assert (await _reload(db_session, instance.id)).status == "ACTIVE"

    async def test_missing_credentials_is_not_a_confirmation(self, db_session):
        """_check_configured raises before any HTTP call when there's no token."""
        instance = await _instance(db_session)

        def not_configured(self):
            raise ValueError("DigitalOcean is not configured")

        with patch.object(DigitalOceanService, "_check_configured", not_configured), \
             pytest.raises(InstanceDeletionError):
            await InstanceService(db_session).delete_and_track_instance(instance.id)

        assert (await _reload(db_session, instance.id)).status == "ACTIVE"

    async def test_force_soft_deletes_when_unconfirmed(self, db_session):
        instance = await _instance(db_session)

        with _provider_returns(False):
            ok = await InstanceService(db_session).delete_and_track_instance(
                instance.id, force=True
            )

        assert ok is True
        assert (await _reload(db_session, instance.id)).status == "DELETED"

    async def test_never_provisioned_instance_skips_provider(self, db_session):
        instance = await _instance(db_session, provider_instance_id=None)
        provider = AsyncMock(return_value=False)

        with patch.object(DigitalOceanService, "delete_instance", new=provider):
            ok = await InstanceService(db_session).delete_and_track_instance(instance.id)

        assert ok is True
        provider.assert_not_awaited()
        assert (await _reload(db_session, instance.id)).status == "DELETED"

    async def test_unknown_instance_returns_false(self, db_session):
        assert await InstanceService(db_session).delete_and_track_instance(999999) is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestBulkDelete:

    async def test_unconfirmed_instance_is_reported_not_counted(self, db_session):
        good = await _instance(db_session, name="good", provider_instance_id="droplet-good")
        bad = await _instance(db_session, name="bad", provider_instance_id="droplet-bad")
        good_id, bad_id = good.id, bad.id  # _reload expires the ORM objects

        async def confirm_only_good(self, droplet_id):
            return droplet_id == "droplet-good"

        with patch.object(DigitalOceanService, "delete_instance", new=confirm_only_good):
            successes, errors = await InstanceService(db_session).bulk_delete_instances(
                [good_id, bad_id]
            )

        assert successes == 1
        assert len(errors) == 1
        assert f"Instance {bad_id}" in errors[0]
        assert "did not confirm" in errors[0]
        assert (await _reload(db_session, good_id)).status == "DELETED"
        assert (await _reload(db_session, bad_id)).status == "ACTIVE"


@pytest.mark.unit
@pytest.mark.asyncio
class TestArchiveReportsInstanceFailures:

    async def test_failures_counted_and_recorded_in_audit(self, db_session):
        event, user = await _seed_archivable_event(db_session)
        instance = await _instance(
            db_session, event_id=event.id, assigned_to_user_id=user.id
        )

        with _provider_returns(False):
            counts = await EventArchiveService(db_session).archive(event.id)

        assert counts["instances_terminated"] == 0
        assert counts["instances_failed"] == 1
        # The VM may still be running, so its row must stay visible.
        assert (await _reload(db_session, instance.id)).status == "ACTIVE"

        audit = (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "EVENT_ARCHIVE")
            )
        ).scalars().all()[-1]
        assert audit.details["instances_failed"] == 1
        assert any("did not confirm" in f for f in audit.details["instance_failures"])

    async def test_already_gone_vm_does_not_count_as_failure(self, db_session):
        event, user = await _seed_archivable_event(db_session)
        await _instance(db_session, event_id=event.id, assigned_to_user_id=user.id)

        with _provider_returns(True):
            counts = await EventArchiveService(db_session).archive(event.id)

        assert counts["instances_terminated"] == 1
        assert counts["instances_failed"] == 0
