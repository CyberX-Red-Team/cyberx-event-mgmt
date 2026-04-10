"""Background VPN bulk-delete job processor.

Mirrors the import job pattern: HTTP handlers create a pending row, a
scheduled task picks it up and runs the delete cooperatively, the admin UI
polls for progress.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.vpn import VPNCredential
from app.models.vpn_delete_job import (
    VPNDeleteJob,
    VPNDeleteJobMode,
    VPNDeleteJobStatus,
)
from app.utils.r2_client import R2Client

logger = logging.getLogger(__name__)


# Process credentials in batches to keep individual SQL statements
# reasonable and to update progress visibly between chunks.
CHUNK_SIZE = 200

# Cap the number of error messages stored on the job row.
MAX_STORED_ERRORS = 50


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VPNDeleteService:
    """Manages the lifecycle of VPN bulk-delete jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.r2 = R2Client.from_settings()
        self.settings = get_settings()

    # ─── public API: HTTP handler entry points ─────────────────────────

    async def queue_delete_by_ids(
        self, vpn_ids: list[int], user_id: Optional[int]
    ) -> VPNDeleteJob:
        """Create a pending bulk-delete job for an explicit id list."""
        if not vpn_ids:
            raise ValueError("No VPN credential IDs provided")
        # Deduplicate and coerce to ints up front so the worker doesn't have
        # to repeat the work and the stored payload is canonical.
        unique_ids = sorted({int(i) for i in vpn_ids})
        job = VPNDeleteJob(
            created_by_user_id=user_id,
            mode=VPNDeleteJobMode.BY_IDS.value,
            target_ids={"items": unique_ids},
            total_credentials=len(unique_ids),
            status=VPNDeleteJobStatus.PENDING.value,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def queue_delete_all(self, user_id: Optional[int]) -> VPNDeleteJob:
        """Create a pending bulk-delete job that targets every credential."""
        job = VPNDeleteJob(
            created_by_user_id=user_id,
            mode=VPNDeleteJobMode.ALL.value,
            target_ids=None,
            status=VPNDeleteJobStatus.PENDING.value,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    # ─── public API: scheduled task entry points ───────────────────────

    async def claim_next_pending_job(self) -> Optional[VPNDeleteJob]:
        """
        Pick the oldest pending delete job. Single-process deployment, so a
        simple ``status='pending'`` filter is sufficient.
        """
        result = await self.session.execute(
            select(VPNDeleteJob)
            .where(VPNDeleteJob.status == VPNDeleteJobStatus.PENDING.value)
            .order_by(VPNDeleteJob.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def process_job(self, job: VPNDeleteJob) -> None:
        """
        Run a pending delete job to completion (or failure).

        Resolves the target id list, then for each chunk:
            1. Bulk-fetch (id, r2_key) for the chunk in one query
            2. Parallel R2 deletes via asyncio.gather + Semaphore, each
               wrapped in to_thread so boto3 does not block the event loop
            3. Single ``DELETE FROM vpn_credentials WHERE id IN (...)`` SQL
            4. Update progress and yield to the event loop
        """
        job.status = VPNDeleteJobStatus.PROCESSING.value
        job.started_at = _utcnow()
        job.processed_credentials = 0
        job.deleted_count = 0
        job.failed_count = 0
        job.errors = {"items": []}
        await self.session.commit()

        try:
            await self._run_delete(job)
        except Exception as e:
            job.status = VPNDeleteJobStatus.FAILED.value
            job.last_error = str(e)
            job.completed_at = _utcnow()
            await self.session.commit()
            logger.exception("VPN delete job %s failed", job.id)
            return

        job.status = VPNDeleteJobStatus.COMPLETED.value
        job.completed_at = _utcnow()
        await self.session.commit()

    async def cleanup_old_jobs(self, retention_days: int) -> int:
        """Delete completed/failed jobs older than the retention window."""
        cutoff = _utcnow() - timedelta(days=retention_days)
        terminal = [
            VPNDeleteJobStatus.COMPLETED.value,
            VPNDeleteJobStatus.FAILED.value,
        ]
        result = await self.session.execute(
            delete(VPNDeleteJob)
            .where(VPNDeleteJob.status.in_(terminal))
            .where(VPNDeleteJob.completed_at.is_not(None))
            .where(VPNDeleteJob.completed_at < cutoff)
        )
        await self.session.commit()
        return result.rowcount or 0

    async def retry_job(self, job_id: int) -> Optional[VPNDeleteJob]:
        """Reset a failed job back to pending so the worker picks it up again."""
        result = await self.session.execute(
            select(VPNDeleteJob).where(VPNDeleteJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None
        if job.status != VPNDeleteJobStatus.FAILED.value:
            return None

        job.status = VPNDeleteJobStatus.PENDING.value
        job.started_at = None
        job.completed_at = None
        job.last_error = None
        job.processed_credentials = 0
        job.deleted_count = 0
        job.failed_count = 0
        job.errors = {"items": []}
        await self.session.commit()
        return job

    async def delete_job(self, job_id: int) -> bool:
        """Delete a completed or failed job. Refuses if currently processing."""
        result = await self.session.execute(
            select(VPNDeleteJob).where(VPNDeleteJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return False
        if job.status == VPNDeleteJobStatus.PROCESSING.value:
            raise ValueError("Cannot delete a job while it is processing")
        await self.session.execute(
            delete(VPNDeleteJob).where(VPNDeleteJob.id == job_id)
        )
        await self.session.commit()
        return True

    # ─── internals ─────────────────────────────────────────────────────

    async def _run_delete(self, job: VPNDeleteJob) -> None:
        """The actual delete work. Resolves targets, then chunks through them."""
        target_ids = await self._resolve_target_ids(job)
        job.total_credentials = len(target_ids)
        await self.session.commit()

        if not target_ids:
            return

        for chunk_start in range(0, len(target_ids), CHUNK_SIZE):
            chunk = target_ids[chunk_start : chunk_start + CHUNK_SIZE]
            await self._process_chunk(chunk, job)
            await self.session.commit()
            await asyncio.sleep(0)  # yield to the event loop

    async def _resolve_target_ids(self, job: VPNDeleteJob) -> list[int]:
        """Build the canonical list of credential ids to delete."""
        if job.mode == VPNDeleteJobMode.ALL.value:
            result = await self.session.execute(
                select(VPNCredential.id).order_by(VPNCredential.id)
            )
            return [row[0] for row in result.all()]

        items = (job.target_ids or {}).get("items") or []
        return [int(i) for i in items]

    async def _process_chunk(self, chunk: list[int], job: VPNDeleteJob) -> None:
        """Delete one batch of credentials and their R2 objects."""
        # Step 1: bulk fetch (id, r2_key) for the chunk so we know which
        # objects to remove from R2.
        result = await self.session.execute(
            select(VPNCredential.id, VPNCredential.r2_key).where(
                VPNCredential.id.in_(chunk)
            )
        )
        rows = list(result.all())
        found_ids = {row[0] for row in rows}
        r2_keys = [row[1] for row in rows if row[1]]

        missing = [i for i in chunk if i not in found_ids]
        for vpn_id in missing:
            self._record_error(job, f"VPN {vpn_id}: Not found")

        # Step 2: parallel R2 deletes — non-fatal if any fail. Each call
        # goes through asyncio.to_thread so boto3 does not block the loop.
        if r2_keys:
            sem = asyncio.Semaphore(self.settings.VPN_IMPORT_R2_PARALLELISM)

            async def _delete_one(key: str) -> tuple[str, bool]:
                async with sem:
                    ok = await asyncio.to_thread(self.r2.delete_object, key)
                return key, ok

            results = await asyncio.gather(
                *(_delete_one(k) for k in r2_keys),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(
                        "R2 delete exception during VPN bulk delete: %s", r
                    )
                elif isinstance(r, tuple):
                    key, ok = r
                    if not ok:
                        logger.warning(
                            "R2 delete returned False for key %s", key
                        )

        # Step 3: bulk delete from the database in one statement
        if found_ids:
            await self.session.execute(
                delete(VPNCredential).where(VPNCredential.id.in_(found_ids))
            )
            job.deleted_count += len(found_ids)

        job.processed_credentials += len(chunk)

    def _record_error(self, job: VPNDeleteJob, message: str) -> None:
        """Append an error to the job's capped error list."""
        job.failed_count += 1
        existing = (job.errors or {}).get("items") or []
        if len(existing) >= MAX_STORED_ERRORS:
            return
        new_items = list(existing)
        new_items.append(message)
        job.errors = {"items": new_items}
