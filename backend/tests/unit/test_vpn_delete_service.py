"""
Unit tests for VPNDeleteService.

Covers job lifecycle, cooperative chunked processing, missing-id error
recording, retry, cleanup, delete-all mode, and the manual delete-job
admin endpoint.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vpn import VPNCredential
from app.models.vpn_delete_job import (
    VPNDeleteJob,
    VPNDeleteJobMode,
    VPNDeleteJobStatus,
)
from app.services.vpn_delete_service import VPNDeleteService
from app.utils.r2_client import R2Client


@pytest.fixture
def mock_r2(monkeypatch):
    """In-memory R2 stand-in shared with the import-service tests."""
    storage: dict[str, bytes] = {}

    class _FakeR2:
        def __init__(self):
            self.bucket = "test-bucket"

        def put_object(self, key, data, content_type=None):
            storage[key] = bytes(data)
            return True

        def get_object(self, key):
            return storage.get(key)

        def delete_object(self, key):
            storage.pop(key, None)
            return True

    monkeypatch.setattr(
        R2Client, "from_settings", classmethod(lambda cls: _FakeR2())
    )
    return storage


def _make_credential(idx: int, with_r2_key: bool = True) -> VPNCredential:
    return VPNCredential(
        interface_ip=f"10.66.66.{idx}/32",
        ipv4_address=f"10.66.66.{idx}",
        private_key=f"privkey-{idx}",
        endpoint="vpn.example.com:51820",
        key_type="vpn",
        is_available=True,
        is_active=True,
        r2_key=f"vpn-configs/{idx}.conf" if with_r2_key else None,
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNDeleteServiceQueueing:
    """HTTP-handler entry points: queue_delete_by_ids / queue_delete_all."""

    async def test_queue_delete_by_ids_creates_pending_job(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNDeleteService(db_session)
        job = await service.queue_delete_by_ids(vpn_ids=[3, 1, 2, 1], user_id=None)
        await db_session.commit()

        assert job.id is not None
        assert job.status == VPNDeleteJobStatus.PENDING.value
        assert job.mode == VPNDeleteJobMode.BY_IDS.value
        # Should be deduped and sorted
        assert job.target_ids == {"items": [1, 2, 3]}
        assert job.total_credentials == 3

    async def test_queue_delete_by_ids_rejects_empty(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNDeleteService(db_session)
        with pytest.raises(ValueError):
            await service.queue_delete_by_ids(vpn_ids=[], user_id=None)

    async def test_queue_delete_all_creates_pending_job(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNDeleteService(db_session)
        job = await service.queue_delete_all(user_id=None)
        await db_session.commit()

        assert job.status == VPNDeleteJobStatus.PENDING.value
        assert job.mode == VPNDeleteJobMode.ALL.value
        assert job.target_ids is None
        assert job.total_credentials is None  # resolved at processing time


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNDeleteServiceProcessing:
    """End-to-end processing of delete jobs."""

    async def test_process_by_ids_deletes_credentials(
        self, db_session: AsyncSession, mock_r2
    ):
        # Pre-seed three credentials
        creds = [_make_credential(i) for i in range(1, 4)]
        db_session.add_all(creds)
        await db_session.commit()
        # Pre-populate fake R2 so we can verify deletes
        for c in creds:
            mock_r2[c.r2_key] = b"x"
        ids = [c.id for c in creds]

        service = VPNDeleteService(db_session)
        job = await service.queue_delete_by_ids(vpn_ids=ids, user_id=None)
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNDeleteJobStatus.COMPLETED.value
        assert job.total_credentials == 3
        assert job.processed_credentials == 3
        assert job.deleted_count == 3
        assert job.failed_count == 0

        # All three credentials are gone from the DB and R2
        result = await db_session.execute(select(VPNCredential))
        assert list(result.scalars().all()) == []
        for c in creds:
            assert c.r2_key not in mock_r2

    async def test_process_records_missing_ids_as_errors(
        self, db_session: AsyncSession, mock_r2
    ):
        c = _make_credential(1)
        db_session.add(c)
        await db_session.commit()
        mock_r2[c.r2_key] = b"x"

        service = VPNDeleteService(db_session)
        job = await service.queue_delete_by_ids(vpn_ids=[c.id, 9999], user_id=None)
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNDeleteJobStatus.COMPLETED.value
        assert job.deleted_count == 1
        assert job.failed_count == 1
        items = (job.errors or {}).get("items", [])
        assert any("9999" in s for s in items)

    async def test_process_skips_r2_for_credentials_without_key(
        self, db_session: AsyncSession, mock_r2
    ):
        c = _make_credential(1, with_r2_key=False)
        db_session.add(c)
        await db_session.commit()

        service = VPNDeleteService(db_session)
        job = await service.queue_delete_by_ids(vpn_ids=[c.id], user_id=None)
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNDeleteJobStatus.COMPLETED.value
        assert job.deleted_count == 1

    async def test_process_delete_all_targets_every_credential(
        self, db_session: AsyncSession, mock_r2
    ):
        creds = [_make_credential(i) for i in range(1, 6)]
        db_session.add_all(creds)
        await db_session.commit()
        for c in creds:
            mock_r2[c.r2_key] = b"x"

        service = VPNDeleteService(db_session)
        job = await service.queue_delete_all(user_id=None)
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNDeleteJobStatus.COMPLETED.value
        assert job.total_credentials == 5
        assert job.deleted_count == 5

        result = await db_session.execute(select(VPNCredential))
        assert list(result.scalars().all()) == []

    async def test_process_chunks_large_id_lists(
        self, db_session: AsyncSession, mock_r2
    ):
        # 250 credentials > CHUNK_SIZE (200) — should require two chunks
        creds = [_make_credential(i) for i in range(1, 251)]
        db_session.add_all(creds)
        await db_session.commit()
        ids = [c.id for c in creds]

        service = VPNDeleteService(db_session)
        job = await service.queue_delete_by_ids(vpn_ids=ids, user_id=None)
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNDeleteJobStatus.COMPLETED.value
        assert job.deleted_count == 250
        assert job.processed_credentials == 250


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNDeleteServiceClaim:
    """Job claiming."""

    async def test_claim_returns_oldest_pending(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNDeleteService(db_session)
        older = await service.queue_delete_by_ids(vpn_ids=[1], user_id=None)
        await db_session.commit()
        older.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        await db_session.commit()

        await service.queue_delete_by_ids(vpn_ids=[2], user_id=None)
        await db_session.commit()

        claimed = await service.claim_next_pending_job()
        assert claimed is not None
        assert claimed.id == older.id

    async def test_claim_returns_none_when_no_pending(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNDeleteService(db_session)
        claimed = await service.claim_next_pending_job()
        assert claimed is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNDeleteServiceCleanup:
    """Retention cleanup."""

    async def test_cleanup_deletes_old_completed_jobs(
        self, db_session: AsyncSession, mock_r2
    ):
        old = VPNDeleteJob(
            mode=VPNDeleteJobMode.BY_IDS.value,
            status=VPNDeleteJobStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        fresh = VPNDeleteJob(
            mode=VPNDeleteJobMode.BY_IDS.value,
            status=VPNDeleteJobStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add_all([old, fresh])
        await db_session.commit()

        service = VPNDeleteService(db_session)
        deleted = await service.cleanup_old_jobs(retention_days=30)
        assert deleted == 1

        result = await db_session.execute(select(VPNDeleteJob))
        remaining = list(result.scalars().all())
        assert len(remaining) == 1
        assert remaining[0].id == fresh.id


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNDeleteServiceRetryAndDelete:
    """Retry and manual job-row delete behaviors."""

    async def test_retry_failed_job(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNDeleteService(db_session)
        job = await service.queue_delete_by_ids(vpn_ids=[1, 2], user_id=None)
        await db_session.commit()

        job.status = VPNDeleteJobStatus.FAILED.value
        job.last_error = "boom"
        await db_session.commit()

        result = await service.retry_job(job.id)
        assert result is not None
        assert result.status == VPNDeleteJobStatus.PENDING.value
        assert result.last_error is None

    async def test_retry_non_failed_returns_none(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNDeleteService(db_session)
        job = await service.queue_delete_by_ids(vpn_ids=[1], user_id=None)
        await db_session.commit()

        result = await service.retry_job(job.id)
        assert result is None

    async def test_delete_completed_job(
        self, db_session: AsyncSession, mock_r2
    ):
        job = VPNDeleteJob(
            mode=VPNDeleteJobMode.BY_IDS.value,
            status=VPNDeleteJobStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add(job)
        await db_session.commit()

        service = VPNDeleteService(db_session)
        ok = await service.delete_job(job.id)
        assert ok is True

        result = await db_session.execute(
            select(VPNDeleteJob).where(VPNDeleteJob.id == job.id)
        )
        assert result.scalar_one_or_none() is None

    async def test_delete_processing_job_refuses(
        self, db_session: AsyncSession, mock_r2
    ):
        job = VPNDeleteJob(
            mode=VPNDeleteJobMode.BY_IDS.value,
            status=VPNDeleteJobStatus.PROCESSING.value,
        )
        db_session.add(job)
        await db_session.commit()

        service = VPNDeleteService(db_session)
        with pytest.raises(ValueError):
            await service.delete_job(job.id)
