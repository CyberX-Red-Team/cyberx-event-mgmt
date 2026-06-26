"""Event archive cascade.

Archiving an event is a destructive multi-step operation that:
  - cancels scheduled APScheduler jobs tied to the event
  - terminates provider VMs (OpenStack/DigitalOcean) and soft-marks instance rows
  - hard-deletes VPN credentials (DB row + R2 config file)
  - hard-deletes TLS certificates (DB row + R2 cert bundle + R2 encrypted key)
  - tears down the per-event step-ca (Render service stop + R2 signing material)
  - purges pending email queue rows whose user is an event participant
  - splits Discord invites: verified→null immediately; unverified→leave for the
    external Discord bot to revoke via GET/POST /api/bot/invites endpoints
  - resets per-event workflow fields on participant User rows via the existing
    bulk_reset_workflow_state method (reset_event_participation=False,
    reset_credentials=False — we preserve history + pandas passwords)
  - clears pending PasswordSyncQueue rows for participants and flips
    User.keycloak_synced=False on those users
  - detaches instance templates by nulling their event_id (templates become
    reusable across events)

Preserved on archive:
  - CPECertificate, ParticipantAction, AuditLog, InstanceTemplate (row kept),
    Redirector, EventParticipation rows, PasswordSyncQueue(synced=True),
    User identity fields.

Every external call wraps its own idempotency (404/NoSuchKey → success) and
honors STAGING_STUB_EXTERNALS which short-circuits the real API call while
leaving DB mutations intact, so the cascade can be iterated against a
staging DB restored from a prod dump.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_queue import EmailQueue, EmailQueueStatus
from app.models.event import Event, EventParticipation
from app.models.instance import Instance
from app.models.instance_template import InstanceTemplate
from app.models.password_sync_queue import PasswordSyncQueue
from app.models.tls_certificate import CAChain, TLSCertificate
from app.models.user import User
from app.models.vpn import VPNCredential
from app.services.audit_service import AuditService
from app.services.email_queue_service import EmailQueueService
from app.services.instance_service import InstanceService
from app.services.participant_service import ParticipantService
from app.services.stepca_service import StepCAService
from app.services.vpn_service import VPNService
from app.tasks.scheduler import get_scheduler
from app.utils.external_stubs import externals_stubbed

logger = logging.getLogger(__name__)


class EventArchiveService:
    """Orchestrates the full archive cascade for an event."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def archive(
        self,
        event_id: int,
        *,
        dry_run: bool = False,
        actor_user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> dict:
        """Run the archive cascade. When dry_run=True, mutations are skipped
        but counts are still computed for the preview modal.

        Returns a counts dict with keys:
            jobs_cancelled, instances_terminated, vpn_creds_deleted,
            tls_certs_deleted, ca_chains_destroyed, emails_purged,
            invites_nulled_used, invites_queued_for_bot, users_reset,
            sync_queue_cleared, templates_detached, participant_count
        """
        event = await self.session.get(Event, event_id)
        if not event:
            raise ValueError(f"Event {event_id} not found")

        # Snapshot participant ids (plain ints) before any mutation, so we
        # don't depend on ORM objects that a mid-cascade rollback could detach.
        participant_user_ids = list(
            (
                await self.session.execute(
                    select(EventParticipation.user_id).where(
                        EventParticipation.event_id == event_id
                    )
                )
            ).scalars().all()
        )

        counts = {
            "jobs_cancelled": 0,
            "instances_terminated": 0,
            "vpn_creds_deleted": 0,
            "tls_certs_deleted": 0,
            "ca_chains_destroyed": 0,
            "emails_purged": 0,
            "invites_nulled_used": 0,
            "invites_queued_for_bot": 0,
            "users_reset": 0,
            "sync_queue_cleared": 0,
            "templates_detached": 0,
            "participant_count": len(participant_user_ids),
        }

        # Every step is best-effort: _safe logs the failure, rolls back any
        # poisoned transaction, and returns a default so the cascade always
        # proceeds to the archive-flag + audit steps. This prevents a single
        # step crash from leaving infra deleted but the event un-archived.
        counts["jobs_cancelled"] = await self._safe(
            "jobs", self._cancel_scheduler_jobs(event_id, dry_run))

        instance_ids = await self._safe(
            "collect_instances", self._collect_instance_ids(event_id), default=[])
        counts["instances_terminated"] = await self._safe(
            "instances", self._terminate_instances(instance_ids, dry_run))

        vpn_ids = await self._safe(
            "collect_vpn", self._collect_vpn_ids(instance_ids, participant_user_ids),
            default=[])
        counts["vpn_creds_deleted"] = await self._safe(
            "vpn", self._delete_vpn_credentials(vpn_ids, dry_run))

        counts["tls_certs_deleted"] = await self._safe(
            "tls", self._delete_tls_certificates(event_id, dry_run))
        counts["ca_chains_destroyed"] = await self._safe(
            "ca", self._teardown_ca_chains(event_id, dry_run))
        counts["emails_purged"] = await self._safe(
            "emails", self._purge_email_queue(participant_user_ids, dry_run))

        nulled_used, queued_for_bot = await self._safe(
            "discord", self._handle_discord_invites(event_id, dry_run), default=(0, 0))
        counts["invites_nulled_used"] = nulled_used
        counts["invites_queued_for_bot"] = queued_for_bot

        counts["users_reset"] = await self._safe(
            "reset", self._reset_participants(participant_user_ids, dry_run))
        counts["sync_queue_cleared"] = await self._safe(
            "sync", self._clear_keycloak_sync(participant_user_ids, dry_run))
        counts["templates_detached"] = await self._safe(
            "templates", self._detach_templates(event_id, dry_run))

        # 10. Archive flags + audit (skipped on dry_run). Re-fetch the event in
        # case an earlier step's rollback expired the original instance.
        if not dry_run:
            event = await self.session.get(Event, event_id)
            event.is_archived = True
            event.archived_at = datetime.now(timezone.utc)
            await self.session.commit()

            audit = AuditService(self.session)
            extra = dict(counts)
            if externals_stubbed():
                extra["externals_stubbed"] = True
            await audit.log_event_archive(
                user_id=actor_user_id or 0,
                event_id=event_id,
                ip_address=ip_address,
                user_agent=user_agent,
                extra_details=extra,
            )

        return counts

    async def _safe(self, label: str, coro, default=0):
        """Await a step coroutine; on failure log, roll back any poisoned
        transaction so later steps can still commit, and return default."""
        try:
            return await coro
        except Exception as e:
            logger.error("Archive step '%s' failed: %s", label, e)
            try:
                await self.session.rollback()
            except Exception:
                pass
            return default

    async def _collect_instance_ids(self, event_id: int) -> list[int]:
        return list(
            (
                await self.session.execute(
                    select(Instance.id).where(
                        Instance.event_id == event_id,
                        Instance.status != "DELETED",
                    )
                )
            ).scalars().all()
        )

    # ------------------------------------------------------------------
    # Step helpers. Each wraps its body in try/except: a step's failure
    # is logged but does not abort the cascade — the next step still runs.
    # ------------------------------------------------------------------

    async def _cancel_scheduler_jobs(self, event_id: int, dry_run: bool) -> int:
        try:
            scheduler = get_scheduler()
            found = 0
            for suffix in ("test", "prod"):
                job_id = f"invitation_emails_event_{event_id}_{suffix}"
                if scheduler.get_job(job_id):
                    found += 1
                    if not dry_run:
                        try:
                            scheduler.remove_job(job_id)
                        except Exception as e:  # JobLookupError or similar
                            logger.info("Job %s already absent: %s", job_id, e)
            return found
        except Exception as e:
            logger.error("Failed to cancel scheduler jobs for event %d: %s", event_id, e)
            return 0

    async def _terminate_instances(
        self, instance_ids: list[int], dry_run: bool
    ) -> int:
        if not instance_ids:
            return 0
        if dry_run:
            return len(instance_ids)
        try:
            service = InstanceService(self.session)
            successes, errors = await service.bulk_delete_instances(instance_ids)
            for err in errors:
                logger.warning("Instance termination error during archive: %s", err)
            return successes
        except Exception as e:
            logger.error("Instance termination failed: %s", e)
            return 0

    async def _collect_vpn_ids(
        self, instance_ids: list[int], participant_user_ids: list[int]
    ) -> list[int]:
        """VPNs attached to this event's instances OR assigned to participants."""
        filters = []
        if instance_ids:
            filters.append(VPNCredential.assigned_to_instance_id.in_(instance_ids))
        if participant_user_ids:
            filters.append(VPNCredential.assigned_to_user_id.in_(participant_user_ids))
        if not filters:
            return []
        from sqlalchemy import or_

        rows = (
            await self.session.execute(
                select(VPNCredential.id).where(or_(*filters))
            )
        ).scalars().all()
        return list(rows)

    async def _delete_vpn_credentials(self, vpn_ids: list[int], dry_run: bool) -> int:
        if not vpn_ids:
            return 0
        if dry_run:
            return len(vpn_ids)
        try:
            service = VPNService(self.session)
            deleted, failed, errors = await service.delete_credentials(vpn_ids)
            for err in errors:
                logger.warning("VPN deletion error during archive: %s", err)
            return deleted
        except Exception as e:
            logger.error("VPN credential deletion failed: %s", e)
            return 0

    async def _delete_tls_certificates(self, event_id: int, dry_run: bool) -> int:
        certs = (
            await self.session.execute(
                select(TLSCertificate).where(TLSCertificate.event_id == event_id)
            )
        ).scalars().all()
        if not certs:
            return 0
        if dry_run:
            return len(certs)
        try:
            stepca = StepCAService()
            deleted = 0
            for cert in certs:
                if cert.cert_bundle_r2_key:
                    stepca.delete_from_r2(cert.cert_bundle_r2_key)
                if cert.private_key_r2_key:
                    stepca.delete_from_r2(cert.private_key_r2_key)
                await self.session.delete(cert)
                deleted += 1
            await self.session.commit()
            return deleted
        except Exception as e:
            logger.error("TLS certificate deletion failed: %s", e)
            return 0

    async def _teardown_ca_chains(self, event_id: int, dry_run: bool) -> int:
        chains = (
            await self.session.execute(
                select(CAChain).where(CAChain.event_id == event_id)
            )
        ).scalars().all()
        if not chains:
            return 0
        if dry_run:
            return len(chains)
        destroyed = 0
        stepca = StepCAService()
        for chain in chains:
            try:
                await stepca.delete_instance(chain, self.session)
                if chain.signing_cert_r2_key:
                    stepca.delete_from_r2(chain.signing_cert_r2_key)
                if chain.signing_key_r2_key:
                    stepca.delete_from_r2(chain.signing_key_r2_key)
                if chain.ca_chain_r2_key:
                    stepca.delete_from_r2(chain.ca_chain_r2_key)
                await self.session.delete(chain)
                destroyed += 1
            except Exception as e:
                logger.error("CA chain %d teardown failed: %s", chain.id, e)
        try:
            await self.session.commit()
        except Exception as e:
            logger.error("CA chain commit failed: %s", e)
        return destroyed

    async def _purge_email_queue(
        self, participant_user_ids: list[int], dry_run: bool
    ) -> int:
        if not participant_user_ids:
            return 0
        try:
            rows = (
                await self.session.execute(
                    select(EmailQueue.id).where(
                        EmailQueue.user_id.in_(participant_user_ids),
                        EmailQueue.status == EmailQueueStatus.PENDING,
                    )
                )
            ).scalars().all()
            email_ids = list(rows)
            if not email_ids:
                return 0
            if dry_run:
                return len(email_ids)
            service = EmailQueueService(self.session)
            cancelled, _failed = await service.bulk_cancel_emails(email_ids)
            return cancelled
        except Exception as e:
            logger.error("Email queue purge failed: %s", e)
            return 0

    async def _handle_discord_invites(
        self, event_id: int, dry_run: bool
    ) -> tuple[int, int]:
        parts = (
            await self.session.execute(
                select(EventParticipation).where(
                    EventParticipation.event_id == event_id,
                    EventParticipation.discord_invite_code.is_not(None),
                )
            )
        ).scalars().all()
        nulled_used = 0
        queued_for_bot = 0
        for p in parts:
            if p.discord_verified_at is not None:
                nulled_used += 1
                if not dry_run:
                    # Used invite: already consumed on Discord's side.
                    p.discord_invite_code = None
            else:
                # Leave populated so the external bot can pick it up via
                # /api/bot/invites/pending-revocation and revoke via Discord API.
                queued_for_bot += 1
        if not dry_run and nulled_used:
            try:
                await self.session.commit()
            except Exception as e:
                logger.error("Discord invite null commit failed: %s", e)
                await self.session.rollback()
        return nulled_used, queued_for_bot

    async def _reset_participants(
        self, participant_user_ids: list[int], dry_run: bool
    ) -> int:
        if not participant_user_ids:
            return 0
        if dry_run:
            # Approximate count — reset excludes ADMINs. Query to be accurate.
            from app.models.user import UserRole

            rows = (
                await self.session.execute(
                    select(User.id).where(
                        User.id.in_(participant_user_ids),
                        User.role != UserRole.ADMIN.value,
                    )
                )
            ).scalars().all()
            return len(list(rows))
        try:
            service = ParticipantService(self.session)
            result = await service.bulk_reset_workflow_state(
                reset_event_participation=False,
                reset_credentials=False,
                user_ids=participant_user_ids,
            )
            return result.get("affected_count", 0)
        except Exception as e:
            logger.error("Participant workflow reset failed: %s", e)
            return 0

    async def _clear_keycloak_sync(
        self, participant_user_ids: list[int], dry_run: bool
    ) -> int:
        if not participant_user_ids:
            return 0
        try:
            pending = (
                await self.session.execute(
                    select(PasswordSyncQueue.id).where(
                        PasswordSyncQueue.user_id.in_(participant_user_ids),
                        PasswordSyncQueue.synced == False,  # noqa: E712
                    )
                )
            ).scalars().all()
            cleared = len(list(pending))
            if dry_run:
                return cleared
            if cleared:
                await self.session.execute(
                    delete(PasswordSyncQueue).where(
                        PasswordSyncQueue.user_id.in_(participant_user_ids),
                        PasswordSyncQueue.synced == False,  # noqa: E712
                    )
                )
            await self.session.execute(
                update(User)
                .where(User.id.in_(participant_user_ids))
                .values(keycloak_synced=False)
            )
            await self.session.commit()
            return cleared
        except Exception as e:
            logger.error("Keycloak sync clear failed: %s", e)
            return 0

    async def _detach_templates(self, event_id: int, dry_run: bool) -> int:
        try:
            rows = (
                await self.session.execute(
                    select(InstanceTemplate.id).where(
                        InstanceTemplate.event_id == event_id
                    )
                )
            ).scalars().all()
            count = len(list(rows))
            if dry_run or count == 0:
                return count
            await self.session.execute(
                update(InstanceTemplate)
                .where(InstanceTemplate.event_id == event_id)
                .values(event_id=None)
            )
            await self.session.commit()
            return count
        except Exception as e:
            logger.error("Template detach failed: %s", e)
            return 0

    # ------------------------------------------------------------------
    # Unarchive: flag-only. Cannot restore torn-down infrastructure.
    # ------------------------------------------------------------------

    async def unarchive(
        self,
        event_id: int,
        *,
        actor_user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Event:
        event = await self.session.get(Event, event_id)
        if not event:
            raise ValueError(f"Event {event_id} not found")
        event.is_archived = False
        event.archived_at = None
        await self.session.commit()

        audit = AuditService(self.session)
        await audit.log_event_unarchive(
            user_id=actor_user_id or 0,
            event_id=event_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return event
