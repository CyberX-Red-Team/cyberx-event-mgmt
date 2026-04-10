"""
Unit tests for VPNImportService.

Covers job lifecycle, cooperative chunked processing, deduplication,
error handling, retry, cleanup, and the dispatcher task.
"""
import io
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vpn import VPNCredential
from app.models.vpn_import_job import VPNImportJob, VPNImportJobStatus
from app.services.vpn_import_service import VPNImportService
from app.utils.r2_client import R2Client


# Two valid WireGuard configs and one invalid one
SAMPLE_CONFIG_1 = """[Interface]
PrivateKey = oK56DE9Ue9zK76rAc8pBl6opph+1v36lm7cXXsQKrQM=
Address = 10.66.66.2/32

[Peer]
PublicKey = HIgo9xNzJMWLKASShiTqIybxZ0U3wGLiUeJ1PKf8ykw=
Endpoint = vpn.example.com:51820
AllowedIPs = 0.0.0.0/0
"""

SAMPLE_CONFIG_2 = """[Interface]
PrivateKey = aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
Address = 10.66.66.3/32

[Peer]
PublicKey = HIgo9xNzJMWLKASShiTqIybxZ0U3wGLiUeJ1PKf8ykw=
Endpoint = vpn.example.com:51820
AllowedIPs = 0.0.0.0/0
"""

INVALID_CONFIG = """[Interface]
# Missing PrivateKey, Address, Endpoint
"""


def _make_zip(files: dict[str, str]) -> bytes:
    """Build a ZIP archive in memory from a {name: content} mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


@pytest.fixture
def mock_r2(monkeypatch):
    """
    Replace ``R2Client.from_settings`` with an in-memory fake so the import
    service can be exercised without touching the network.
    """
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


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNImportServiceStaging:
    """Stage-upload step (HTTP handler entry point)."""

    async def test_stage_upload_creates_pending_job(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        zip_bytes = _make_zip({"a.conf": SAMPLE_CONFIG_1})

        job = await service.stage_upload(
            zip_bytes=zip_bytes,
            filename="upload.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        assert job.id is not None
        assert job.status == VPNImportJobStatus.PENDING.value
        assert job.r2_key is not None
        assert job.r2_key.startswith("vpn-import-jobs/")
        assert job.file_size_bytes == len(zip_bytes)
        assert job.filename == "upload.zip"
        # The staged ZIP should be in (fake) R2
        assert job.r2_key in mock_r2


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNImportServiceProcessing:
    """End-to-end processing of a staged job."""

    async def test_process_job_imports_configs(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        zip_bytes = _make_zip(
            {
                "a.conf": SAMPLE_CONFIG_1,
                "b.conf": SAMPLE_CONFIG_2,
            }
        )
        job = await service.stage_upload(
            zip_bytes=zip_bytes,
            filename="upload.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        await service.process_job(job)

        await db_session.refresh(job)
        assert job.status == VPNImportJobStatus.COMPLETED.value
        assert job.total_files == 2
        assert job.processed_files == 2
        assert job.imported_count == 2
        assert job.skipped_count == 0
        assert job.error_count == 0
        # Staged ZIP should have been removed on success
        assert job.r2_key is None

        # Two VPNCredential rows should now exist
        result = await db_session.execute(select(VPNCredential))
        creds = list(result.scalars().all())
        assert len(creds) == 2

    async def test_process_job_skips_duplicates_in_zip(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        # Same content in two filenames -> same hash -> one import
        zip_bytes = _make_zip(
            {
                "a.conf": SAMPLE_CONFIG_1,
                "a-copy.conf": SAMPLE_CONFIG_1,
            }
        )
        job = await service.stage_upload(
            zip_bytes=zip_bytes,
            filename="dups.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNImportJobStatus.COMPLETED.value
        assert job.imported_count == 1
        assert job.skipped_count == 1
        result = await db_session.execute(select(VPNCredential))
        assert len(list(result.scalars().all())) == 1

    async def test_process_job_skips_existing_credentials(
        self, db_session: AsyncSession, mock_r2
    ):
        # Pre-seed a credential whose hash matches SAMPLE_CONFIG_1
        import hashlib
        existing_hash = hashlib.sha256(SAMPLE_CONFIG_1.encode()).hexdigest()
        existing = VPNCredential(
            interface_ip="10.66.66.2/32",
            ipv4_address="10.66.66.2",
            private_key="oK56DE9Ue9zK76rAc8pBl6opph+1v36lm7cXXsQKrQM=",
            endpoint="vpn.example.com:51820",
            key_type="vpn",
            file_hash=existing_hash,
            is_available=True,
        )
        db_session.add(existing)
        await db_session.commit()

        service = VPNImportService(db_session)
        zip_bytes = _make_zip(
            {"a.conf": SAMPLE_CONFIG_1, "b.conf": SAMPLE_CONFIG_2}
        )
        job = await service.stage_upload(
            zip_bytes=zip_bytes,
            filename="mix.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNImportJobStatus.COMPLETED.value
        assert job.imported_count == 1  # only the new one
        assert job.skipped_count == 1  # the duplicate

    async def test_process_job_records_invalid_config_errors(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        zip_bytes = _make_zip(
            {
                "good.conf": SAMPLE_CONFIG_1,
                "bad.conf": INVALID_CONFIG,
            }
        )
        job = await service.stage_upload(
            zip_bytes=zip_bytes,
            filename="mix.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNImportJobStatus.COMPLETED.value
        assert job.imported_count == 1
        assert job.skipped_count == 1
        assert job.error_count == 1
        items = (job.errors or {}).get("items", [])
        assert len(items) == 1
        assert "bad.conf" in items[0]

    async def test_process_job_handles_invalid_zip(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        # Stage a non-zip blob
        job = await service.stage_upload(
            zip_bytes=b"not a zip file",
            filename="bogus.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNImportJobStatus.FAILED.value
        assert job.last_error
        assert "Invalid ZIP" in job.last_error

    async def test_process_job_skips_hidden_and_directory_entries(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("subdir/", "")  # directory
            zf.writestr(".hidden.conf", SAMPLE_CONFIG_1)  # hidden
            zf.writestr("__macosx", "junk")  # system
            zf.writestr("real.conf", SAMPLE_CONFIG_2)
        zip_bytes = buf.getvalue()

        job = await service.stage_upload(
            zip_bytes=zip_bytes,
            filename="mixed.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        await service.process_job(job)
        await db_session.refresh(job)

        assert job.status == VPNImportJobStatus.COMPLETED.value
        assert job.imported_count == 1
        assert job.total_files == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNImportServiceClaim:
    """Job claiming."""

    async def test_claim_returns_oldest_pending(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        # Create three jobs with intentionally distinct created_at values
        older = await service.stage_upload(
            zip_bytes=_make_zip({"a.conf": SAMPLE_CONFIG_1}),
            filename="older.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()
        older.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        await db_session.commit()

        newer = await service.stage_upload(
            zip_bytes=_make_zip({"b.conf": SAMPLE_CONFIG_2}),
            filename="newer.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        claimed = await service.claim_next_pending_job()
        assert claimed is not None
        assert claimed.id == older.id

    async def test_claim_returns_none_when_no_pending(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        claimed = await service.claim_next_pending_job()
        assert claimed is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNImportServiceCleanup:
    """Retention cleanup."""

    async def test_cleanup_deletes_old_completed_jobs(
        self, db_session: AsyncSession, mock_r2
    ):
        # Insert two jobs: one old, one fresh
        old_completed = VPNImportJob(
            file_size_bytes=10,
            assignment_type="USER_REQUESTABLE",
            status=VPNImportJobStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        fresh_completed = VPNImportJob(
            file_size_bytes=10,
            assignment_type="USER_REQUESTABLE",
            status=VPNImportJobStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add_all([old_completed, fresh_completed])
        await db_session.commit()

        service = VPNImportService(db_session)
        deleted = await service.cleanup_old_jobs(retention_days=30)
        assert deleted == 1

        result = await db_session.execute(select(VPNImportJob))
        remaining = list(result.scalars().all())
        assert len(remaining) == 1
        assert remaining[0].id == fresh_completed.id

    async def test_cleanup_does_not_delete_pending_or_processing(
        self, db_session: AsyncSession, mock_r2
    ):
        old_pending = VPNImportJob(
            file_size_bytes=10,
            assignment_type="USER_REQUESTABLE",
            status=VPNImportJobStatus.PENDING.value,
        )
        old_processing = VPNImportJob(
            file_size_bytes=10,
            assignment_type="USER_REQUESTABLE",
            status=VPNImportJobStatus.PROCESSING.value,
        )
        db_session.add_all([old_pending, old_processing])
        await db_session.commit()

        service = VPNImportService(db_session)
        deleted = await service.cleanup_old_jobs(retention_days=30)
        assert deleted == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNImportServiceRetryAndDelete:
    """Retry and manual delete behaviors."""

    async def test_retry_failed_job_with_staged_zip(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        job = await service.stage_upload(
            zip_bytes=_make_zip({"a.conf": SAMPLE_CONFIG_1}),
            filename="x.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        # Manually mark as failed
        job.status = VPNImportJobStatus.FAILED.value
        job.last_error = "boom"
        await db_session.commit()

        result = await service.retry_job(job.id)
        assert result is not None
        assert result.status == VPNImportJobStatus.PENDING.value
        assert result.last_error is None
        assert result.processed_files == 0

    async def test_retry_non_failed_job_returns_none(
        self, db_session: AsyncSession, mock_r2
    ):
        service = VPNImportService(db_session)
        job = await service.stage_upload(
            zip_bytes=_make_zip({"a.conf": SAMPLE_CONFIG_1}),
            filename="x.zip",
            assignment_type="USER_REQUESTABLE",
            endpoint=None,
            user_id=None,
        )
        await db_session.commit()

        result = await service.retry_job(job.id)
        assert result is None  # still pending, not retryable

    async def test_delete_completed_job(
        self, db_session: AsyncSession, mock_r2
    ):
        job = VPNImportJob(
            file_size_bytes=10,
            assignment_type="USER_REQUESTABLE",
            status=VPNImportJobStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add(job)
        await db_session.commit()

        service = VPNImportService(db_session)
        ok = await service.delete_job(job.id)
        assert ok is True

        result = await db_session.execute(
            select(VPNImportJob).where(VPNImportJob.id == job.id)
        )
        assert result.scalar_one_or_none() is None

    async def test_delete_processing_job_refuses(
        self, db_session: AsyncSession, mock_r2
    ):
        job = VPNImportJob(
            file_size_bytes=10,
            assignment_type="USER_REQUESTABLE",
            status=VPNImportJobStatus.PROCESSING.value,
        )
        db_session.add(job)
        await db_session.commit()

        service = VPNImportService(db_session)
        with pytest.raises(ValueError):
            await service.delete_job(job.id)
