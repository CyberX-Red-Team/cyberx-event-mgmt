"""Background VPN import job processor.

This service drives the asynchronous VPN credential import flow:

1. ``stage_upload`` is called from the HTTP handler — it uploads the raw ZIP
   to R2 and creates a ``VPNImportJob`` row in ``pending`` state. The HTTP
   request returns immediately.
2. ``vpn_import_job`` (a scheduled task) calls ``claim_next_pending_job``
   followed by ``process_job`` to do the actual work in the background.
3. ``process_job`` parses the ZIP cooperatively, deduplicating against the
   existing VPN pool and uploading per-credential configs to R2 in parallel.
   It yields to the event loop between chunks so other HTTP requests can
   make progress.
4. ``cleanup_old_jobs`` (a daily scheduled task) deletes completed and
   failed jobs older than ``VPN_IMPORT_RETENTION_DAYS`` so the table does
   not grow forever.
"""
import asyncio
import hashlib
import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.vpn import VPNCredential
from app.models.vpn_import_job import VPNImportJob, VPNImportJobStatus
from app.services.vpn_service import (
    VPNService,
    parse_wireguard_config,
    split_addresses,
)
from app.utils.r2_client import R2Client

logger = logging.getLogger(__name__)


# Process this many ZIP entries per chunk before yielding to the event loop.
# Smaller chunks = more responsive HTTP serving, more frequent progress
# updates. Larger chunks = fewer commits and more efficient bulk inserts.
CHUNK_SIZE = 100

# Cap the number of error messages stored on the job row so a malformed ZIP
# does not blow up the JSON column.
MAX_STORED_ERRORS = 50


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _r2_staged_key(uid: str) -> str:
    return f"vpn-import-jobs/{uid}.zip"


def _should_skip_zip_entry(name: str) -> bool:
    """True if a ZIP entry should be silently ignored (directory, hidden, system)."""
    if name.endswith("/"):
        return True
    basename = name.rsplit("/", 1)[-1]
    if basename.startswith(".") or basename.startswith("__"):
        return True
    return False


class VPNImportService:
    """Manages the lifecycle of VPN import jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.r2 = R2Client.from_settings()
        self.settings = get_settings()

    # ─── public API: HTTP handler entry point ──────────────────────────

    async def stage_upload(
        self,
        zip_bytes: bytes,
        filename: Optional[str],
        assignment_type: str,
        endpoint: Optional[str],
        user_id: Optional[int],
    ) -> VPNImportJob:
        """
        Upload the raw ZIP to R2 and create a pending import job.

        Returns the persisted ``VPNImportJob``. The caller is responsible for
        ``commit()``-ing the surrounding transaction.
        """
        uid = uuid4().hex
        r2_key = _r2_staged_key(uid)

        ok = await asyncio.to_thread(
            self.r2.put_object, r2_key, zip_bytes, "application/zip"
        )
        if not ok:
            raise RuntimeError("Failed to stage VPN import upload to R2")

        job = VPNImportJob(
            created_by_user_id=user_id,
            filename=filename,
            file_size_bytes=len(zip_bytes),
            assignment_type=assignment_type,
            endpoint_override=endpoint,
            r2_key=r2_key,
            status=VPNImportJobStatus.PENDING.value,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    # ─── public API: scheduled task entry points ───────────────────────

    async def claim_next_pending_job(self) -> Optional[VPNImportJob]:
        """
        Pick the oldest pending job. Single-process deployment, so a simple
        ``status='pending'`` filter is sufficient — no row-level locking
        required.
        """
        result = await self.session.execute(
            select(VPNImportJob)
            .where(VPNImportJob.status == VPNImportJobStatus.PENDING.value)
            .order_by(VPNImportJob.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def process_job(self, job: VPNImportJob) -> None:
        """
        Run a pending job to completion (or to failure).

        Updates progress columns after each chunk so the polling UI can show
        a live progress bar. On exception, marks the job as failed and
        re-raises so the caller's logger sees the traceback.
        """
        job.status = VPNImportJobStatus.PROCESSING.value
        job.started_at = _utcnow()
        job.processed_files = 0
        job.imported_count = 0
        job.skipped_count = 0
        job.error_count = 0
        job.errors = {"items": []}
        await self.session.commit()

        try:
            await self._run_import(job)
        except Exception as e:
            job.status = VPNImportJobStatus.FAILED.value
            job.last_error = str(e)
            job.completed_at = _utcnow()
            await self.session.commit()
            logger.exception("VPN import job %s failed", job.id)
            return

        # Success path: mark complete and clean up the staged ZIP
        job.status = VPNImportJobStatus.COMPLETED.value
        job.completed_at = _utcnow()
        await self.session.commit()

        if job.r2_key:
            staged_key = job.r2_key
            try:
                await asyncio.to_thread(self.r2.delete_object, staged_key)
            except Exception as e:
                logger.warning(
                    "Failed to delete staged VPN import ZIP %s: %s", staged_key, e
                )
            job.r2_key = None
            await self.session.commit()

    async def cleanup_old_jobs(self, retention_days: int) -> int:
        """
        Delete completed/failed jobs whose ``completed_at`` is older than the
        retention window. Returns the number of rows removed.
        """
        cutoff = _utcnow() - timedelta(days=retention_days)
        terminal = [
            VPNImportJobStatus.COMPLETED.value,
            VPNImportJobStatus.FAILED.value,
        ]
        result = await self.session.execute(
            delete(VPNImportJob)
            .where(VPNImportJob.status.in_(terminal))
            .where(VPNImportJob.completed_at.is_not(None))
            .where(VPNImportJob.completed_at < cutoff)
        )
        await self.session.commit()
        return result.rowcount or 0

    async def retry_job(self, job_id: int) -> Optional[VPNImportJob]:
        """
        Reset a failed job back to ``pending`` so the worker picks it up
        again. Returns the updated job, or None if not found / not eligible.
        """
        result = await self.session.execute(
            select(VPNImportJob).where(VPNImportJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None
        if job.status != VPNImportJobStatus.FAILED.value:
            return None
        if not job.r2_key:
            # Staged ZIP was deleted on prior success path; can't replay.
            job.last_error = (
                "Cannot retry — staged upload no longer available. Re-upload required."
            )
            await self.session.commit()
            return job

        job.status = VPNImportJobStatus.PENDING.value
        job.started_at = None
        job.completed_at = None
        job.last_error = None
        job.processed_files = 0
        job.imported_count = 0
        job.skipped_count = 0
        job.error_count = 0
        job.errors = {"items": []}
        await self.session.commit()
        return job

    async def delete_job(self, job_id: int) -> bool:
        """
        Delete a completed or failed job (and any staged R2 object).
        Refuses to delete a job that is currently processing.
        """
        result = await self.session.execute(
            select(VPNImportJob).where(VPNImportJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return False
        if job.status == VPNImportJobStatus.PROCESSING.value:
            raise ValueError("Cannot delete a job while it is processing")

        if job.r2_key:
            try:
                await asyncio.to_thread(self.r2.delete_object, job.r2_key)
            except Exception as e:
                logger.warning(
                    "Failed to delete staged VPN import ZIP %s: %s", job.r2_key, e
                )

        await self.session.execute(
            delete(VPNImportJob).where(VPNImportJob.id == job_id)
        )
        await self.session.commit()
        return True

    # ─── internals ─────────────────────────────────────────────────────

    async def _run_import(self, job: VPNImportJob) -> None:
        """The actual import work, called from process_job inside a try/except."""
        if not job.r2_key:
            raise RuntimeError("Job has no staged ZIP to process")

        zip_bytes = await asyncio.to_thread(self.r2.get_object, job.r2_key)
        if zip_bytes is None:
            raise RuntimeError(f"Could not download staged ZIP {job.r2_key}")

        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
        except zipfile.BadZipFile as e:
            raise RuntimeError(f"Invalid ZIP file: {e}")

        with zf:
            entries = [n for n in zf.namelist() if not _should_skip_zip_entry(n)]
            job.total_files = len(entries)
            await self.session.commit()

            for chunk_start in range(0, len(entries), CHUNK_SIZE):
                chunk = entries[chunk_start : chunk_start + CHUNK_SIZE]
                await self._process_chunk(zf, chunk, job)
                await self.session.commit()
                # Yield to the event loop so HTTP requests can make progress
                await asyncio.sleep(0)

    async def _process_chunk(
        self,
        zf: zipfile.ZipFile,
        chunk: list[str],
        job: VPNImportJob,
    ) -> None:
        """
        Parse, dedup, insert, and R2-upload one batch of ZIP entries.

        Reads each entry from the ZIP (synchronous, but in-memory and fast),
        parses it via the pure ``parse_wireguard_config`` helper, and then:
            - Bulk-checks the file_hash set against existing rows in one query
            - Inserts non-duplicates with ``add_all`` + ``flush`` (one DB
              round-trip for the whole chunk)
            - Uploads the per-credential configs to R2 in parallel via
              ``asyncio.gather`` with a concurrency limit
        """
        # Step 1: parse all entries in the chunk
        parsed_records: list[dict] = []
        for filename in chunk:
            try:
                raw = zf.read(filename)
                try:
                    config_text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    job.skipped_count += 1
                    continue

                parsed = parse_wireguard_config(
                    config_text, endpoint_override=job.endpoint_override
                )
                file_hash = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
                parsed_records.append(
                    {
                        "filename": filename,
                        "config_text": config_text,
                        "file_hash": file_hash,
                        "parsed": parsed,
                    }
                )
            except ValueError as e:
                self._record_error(job, filename, str(e))
            except Exception as e:
                logger.warning("Unexpected error parsing %s: %s", filename, e)
                self._record_error(job, filename, str(e))

        if not parsed_records:
            job.processed_files += len(chunk)
            return

        # Step 2: dedup against existing credentials in one query
        hashes = [r["file_hash"] for r in parsed_records]
        existing_result = await self.session.execute(
            select(VPNCredential.file_hash).where(VPNCredential.file_hash.in_(hashes))
        )
        existing_hashes = {row[0] for row in existing_result.all()}

        # Also dedup within the chunk itself (same file present twice)
        seen_in_chunk: set[str] = set()
        new_records: list[dict] = []
        for rec in parsed_records:
            h = rec["file_hash"]
            if h in existing_hashes or h in seen_in_chunk:
                job.skipped_count += 1
                continue
            seen_in_chunk.add(h)
            new_records.append(rec)

        if not new_records:
            job.processed_files += len(chunk)
            return

        # Step 3: build VPNCredential objects and bulk-flush to assign IDs
        new_credentials: list[VPNCredential] = []
        for rec in new_records:
            parsed = rec["parsed"]
            interface_ip, ipv4, ipv6_local, ipv6_global = split_addresses(
                parsed["addresses"]
            )
            vpn = VPNCredential(
                interface_ip=interface_ip,
                ipv4_address=ipv4,
                ipv6_local=ipv6_local,
                ipv6_global=ipv6_global,
                private_key=parsed["private_key"],
                preshared_key=parsed["preshared_key"],
                endpoint=parsed["endpoint"],
                key_type="vpn",
                mtu=parsed["mtu"],
                dns=parsed["dns"],
                public_key=parsed["public_key"],
                allowed_ips=parsed["allowed_ips"],
                persistent_keepalive=parsed["persistent_keepalive"],
                table=parsed["table"],
                save_config=parsed["save_config"],
                fwmark=parsed["fwmark"],
                file_hash=rec["file_hash"],
                assignment_type=job.assignment_type,
                is_available=True,
                is_active=True,
            )
            new_credentials.append(vpn)
            rec["vpn"] = vpn

        self.session.add_all(new_credentials)
        await self.session.flush()  # assigns ids

        # Step 4: parallel R2 uploads, throttled by a semaphore
        sem = asyncio.Semaphore(self.settings.VPN_IMPORT_R2_PARALLELISM)

        async def upload_one(rec: dict) -> tuple[VPNCredential, bool]:
            vpn: VPNCredential = rec["vpn"]
            r2_key = VPNService._make_r2_key(vpn.id)
            payload = rec["config_text"].encode("utf-8")
            async with sem:
                ok = await asyncio.to_thread(
                    self.r2.put_object, r2_key, payload, "text/plain"
                )
            if ok:
                vpn.r2_key = r2_key
            return vpn, ok

        upload_results = await asyncio.gather(
            *(upload_one(rec) for rec in new_records),
            return_exceptions=True,
        )

        for result in upload_results:
            if isinstance(result, Exception):
                logger.warning("R2 upload exception during VPN import: %s", result)
                # Still counts as imported — the lazy fallback in
                # VPNService.get_raw_config will regenerate from DB fields.
                continue

        job.imported_count += len(new_records)
        job.processed_files += len(chunk)

    def _record_error(self, job: VPNImportJob, filename: str, message: str) -> None:
        """Append a per-file error to the job's capped error list."""
        job.error_count += 1
        job.skipped_count += 1
        existing = (job.errors or {}).get("items") or []
        if len(existing) >= MAX_STORED_ERRORS:
            return
        # Always assign a brand-new outer dict + inner list so SQLAlchemy
        # detects the change even when MutableDict tracking is unavailable.
        new_items = list(existing)
        new_items.append(f"{filename}: {message}")
        job.errors = {"items": new_items}
