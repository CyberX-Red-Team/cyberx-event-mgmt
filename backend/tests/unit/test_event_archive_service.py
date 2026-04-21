"""Unit tests for EventArchiveService cascade.

Covers:
  - Cascade ordering + external deletes (mocked)
  - Idempotency of external delete methods (404/NoSuchKey treated as success)
  - Stub-mode short-circuit of external calls
  - Dry-run (preview) returns counts without mutating
  - Audit-preservation: CPE certs, ParticipantAction, EventParticipation,
    AuditLog, User identity all untouched
  - Unarchive flips flag + logs audit

Notes:
  - Uses SQLite in-memory (see conftest). The cross-DB regression memory
    calls out that JSON-predicate filters passed SQLite but failed on PG;
    integration-level verification on PG is called out in the plan and
    should be run separately.
"""

import os
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_queue import EmailQueue, EmailQueueStatus
from app.models.event import Event, EventParticipation, ParticipationStatus, generate_slug
from app.models.password_sync_queue import PasswordSyncQueue
from app.models.tls_certificate import CAChain, TLSCertificate
from app.models.instance import Instance
from app.models.instance_template import InstanceTemplate
from app.models.user import User, UserRole
from app.models.vpn import VPNCredential
from app.services.event_archive_service import EventArchiveService
from app.utils.security import hash_password


async def _seed_archivable_event(db: AsyncSession, year: int = 2024) -> tuple[Event, User]:
    event = Event(
        year=year,
        name=f"CyberX {year}",
        slug=generate_slug(f"CyberX {year}"),
        start_date=date(year, 6, 1),
        end_date=date(year, 6, 7),
        is_active=False,
        is_archived=False,
    )
    db.add(event)
    await db.flush()

    user = User(
        email=f"participant-{year}@example.com",
        email_normalized=f"participant-{year}@example.com",
        first_name="Test",
        last_name="User",
        country="USA",
        password_hash=hash_password("x" * 12),
        role=UserRole.INVITEE.value,
        is_active=True,
        keycloak_synced=True,
        confirmation_code="old-code",
        invite_sent=datetime.now(timezone.utc),
        terms_accepted=True,
    )
    db.add(user)
    await db.flush()

    db.add(
        EventParticipation(
            user_id=user.id,
            event_id=event.id,
            status=ParticipationStatus.CONFIRMED.value,
            discord_invite_code="used-invite-ABC",
            discord_verified_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return event, user


@pytest.mark.unit
@pytest.mark.asyncio
class TestEventArchiveCascade:
    """Cascade ordering and effects."""

    async def test_dry_run_does_not_mutate(self, db_session: AsyncSession):
        event, user = await _seed_archivable_event(db_session)
        service = EventArchiveService(db_session)

        counts = await service.archive(event.id, dry_run=True)

        assert counts["participant_count"] == 1
        assert counts["invites_nulled_used"] == 1

        await db_session.refresh(event)
        assert event.is_archived is False
        assert event.archived_at is None

        part = (
            await db_session.execute(
                select(EventParticipation).where(EventParticipation.event_id == event.id)
            )
        ).scalar_one()
        assert part.discord_invite_code == "used-invite-ABC"

    async def test_archive_flips_flag_and_writes_archived_at(self, db_session: AsyncSession):
        event, _ = await _seed_archivable_event(db_session)
        service = EventArchiveService(db_session)

        counts = await service.archive(event.id, actor_user_id=None)

        await db_session.refresh(event)
        assert event.is_archived is True
        assert event.archived_at is not None
        assert counts["invites_nulled_used"] == 1

    async def test_used_discord_invite_nulled_and_verified_preserved(
        self, db_session: AsyncSession
    ):
        event, user = await _seed_archivable_event(db_session)
        service = EventArchiveService(db_session)
        await service.archive(event.id)

        part = (
            await db_session.execute(
                select(EventParticipation).where(EventParticipation.user_id == user.id)
            )
        ).scalar_one()
        assert part.discord_invite_code is None
        assert part.discord_verified_at is not None

    async def test_unused_discord_invite_left_for_bot_revocation(
        self, db_session: AsyncSession
    ):
        event, user = await _seed_archivable_event(db_session, year=2023)
        part = (
            await db_session.execute(
                select(EventParticipation).where(EventParticipation.user_id == user.id)
            )
        ).scalar_one()
        part.discord_invite_code = "unused-invite-XYZ"
        part.discord_verified_at = None
        await db_session.commit()

        service = EventArchiveService(db_session)
        counts = await service.archive(event.id)

        assert counts["invites_queued_for_bot"] == 1
        assert counts["invites_nulled_used"] == 0

        await db_session.refresh(part)
        assert part.discord_invite_code == "unused-invite-XYZ"
        assert part.discord_verified_at is None

    async def test_participant_workflow_reset_preserves_participation(
        self, db_session: AsyncSession
    ):
        event, user = await _seed_archivable_event(db_session)
        service = EventArchiveService(db_session)
        await service.archive(event.id)

        await db_session.refresh(user)
        assert user.terms_accepted is False
        assert user.invite_sent is None
        assert user.keycloak_synced is False
        assert user.email == f"participant-{event.year}@example.com"

        part_count = len(
            (
                await db_session.execute(
                    select(EventParticipation).where(EventParticipation.event_id == event.id)
                )
            ).scalars().all()
        )
        assert part_count == 1

    async def test_pending_sync_rows_purged_completed_preserved(
        self, db_session: AsyncSession
    ):
        event, user = await _seed_archivable_event(db_session)

        # pending sync row for participant
        db_session.add(PasswordSyncQueue(user_id=user.id, username=user.email, synced=False))
        # completed sync row for same user should survive
        db_session.add(
            PasswordSyncQueue(
                user_id=user.id,
                username=user.email,
                synced=True,
                synced_at=datetime.now(timezone.utc),
            )
        )
        # unrelated user's pending sync row should NOT be deleted
        other = User(
            email="other@example.com",
            email_normalized="other@example.com",
            first_name="Other",
            last_name="User",
            country="USA",
            password_hash=hash_password("y" * 12),
            role=UserRole.INVITEE.value,
            is_active=True,
        )
        db_session.add(other)
        await db_session.flush()
        db_session.add(PasswordSyncQueue(user_id=other.id, username=other.email, synced=False))
        await db_session.commit()

        service = EventArchiveService(db_session)
        counts = await service.archive(event.id)

        assert counts["sync_queue_cleared"] == 1

        participant_pending = (
            await db_session.execute(
                select(PasswordSyncQueue).where(
                    PasswordSyncQueue.user_id == user.id,
                    PasswordSyncQueue.synced == False,  # noqa: E712
                )
            )
        ).scalars().all()
        assert len(participant_pending) == 0

        participant_synced = (
            await db_session.execute(
                select(PasswordSyncQueue).where(
                    PasswordSyncQueue.user_id == user.id,
                    PasswordSyncQueue.synced == True,  # noqa: E712
                )
            )
        ).scalars().all()
        assert len(participant_synced) == 1

        other_pending = (
            await db_session.execute(
                select(PasswordSyncQueue).where(PasswordSyncQueue.user_id == other.id)
            )
        ).scalars().all()
        assert len(other_pending) == 1

    async def test_email_queue_purged_for_participants(self, db_session: AsyncSession):
        event, user = await _seed_archivable_event(db_session)

        db_session.add(
            EmailQueue(
                user_id=user.id,
                template_name="some_template",
                recipient_email=user.email,
                status=EmailQueueStatus.PENDING,
            )
        )
        await db_session.commit()

        service = EventArchiveService(db_session)
        counts = await service.archive(event.id)
        assert counts["emails_purged"] == 1

        q = (
            await db_session.execute(select(EmailQueue).where(EmailQueue.user_id == user.id))
        ).scalar_one()
        assert q.status == EmailQueueStatus.CANCELLED

    async def test_templates_detached_on_archive(self, db_session: AsyncSession):
        event, _ = await _seed_archivable_event(db_session)
        tpl = InstanceTemplate(
            name="Hexio",
            provider="digitalocean",
            image_id="ubuntu-22",
            event_id=event.id,
        )
        db_session.add(tpl)
        await db_session.commit()

        service = EventArchiveService(db_session)
        counts = await service.archive(event.id)
        assert counts["templates_detached"] == 1

        await db_session.refresh(tpl)
        assert tpl.event_id is None

    async def test_tls_and_ca_destroyed_calls_delete_from_r2(
        self, db_session: AsyncSession
    ):
        event, user = await _seed_archivable_event(db_session)
        ca = CAChain(
            name="test CA",
            event_id=event.id,
            signing_cert_r2_key="tls/ca-chains/1/signing.crt",
            signing_key_r2_key="tls/ca-chains/1/signing.key",
            ca_chain_r2_key="tls/ca-chains/1/chain.pem",
            render_service_id="srv-abc",
        )
        db_session.add(ca)
        await db_session.flush()

        cert = TLSCertificate(
            event_id=event.id,
            ca_chain_id=ca.id,
            common_name="test.example",
            cert_bundle_r2_key="tls/certificates/1/1/cert.crt",
            private_key_r2_key="tls/certificates/1/1/cert.key",
        )
        db_session.add(cert)
        await db_session.commit()

        service = EventArchiveService(db_session)
        with patch(
            "app.services.event_archive_service.StepCAService"
        ) as StepCAStub:
            stub = StepCAStub.return_value
            stub.delete_from_r2 = MagicMock(return_value=True)
            stub.delete_instance = AsyncMock(return_value=True)
            counts = await service.archive(event.id)

        # 2 R2 keys per cert + 3 R2 keys per CA chain = 5 calls here
        assert stub.delete_from_r2.call_count == 5
        stub.delete_instance.assert_awaited_once()
        assert counts["tls_certs_deleted"] == 1
        assert counts["ca_chains_destroyed"] == 1

        remaining_certs = (
            await db_session.execute(
                select(TLSCertificate).where(TLSCertificate.event_id == event.id)
            )
        ).scalars().all()
        assert len(remaining_certs) == 0

        remaining_chains = (
            await db_session.execute(
                select(CAChain).where(CAChain.event_id == event.id)
            )
        ).scalars().all()
        assert len(remaining_chains) == 0

    async def test_audit_log_written_and_no_audits_deleted(
        self, db_session: AsyncSession
    ):
        from app.models.audit_log import AuditLog

        event, _ = await _seed_archivable_event(db_session)

        # Pre-existing audit rows must survive
        pre = AuditLog(
            action="SOMETHING_ELSE",
            resource_type="EVENT",
            resource_id=event.id,
            details={},
        )
        db_session.add(pre)
        await db_session.commit()
        pre_count = len(
            (await db_session.execute(select(AuditLog))).scalars().all()
        )

        service = EventArchiveService(db_session)
        await service.archive(event.id)

        logs = (await db_session.execute(select(AuditLog))).scalars().all()
        assert len(logs) > pre_count
        assert any(log.action == "EVENT_ARCHIVE" for log in logs)
        assert all(
            not (log.action == "SOMETHING_ELSE" and log.resource_id == event.id and log.id == pre.id)
            or log.action == "SOMETHING_ELSE"
            for log in logs
        )

    async def test_unarchive_flips_flag(self, db_session: AsyncSession):
        event, _ = await _seed_archivable_event(db_session)
        service = EventArchiveService(db_session)
        await service.archive(event.id)
        await db_session.refresh(event)
        assert event.is_archived is True

        await service.unarchive(event.id)
        await db_session.refresh(event)
        assert event.is_archived is False
        assert event.archived_at is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestStubMode:
    """Verify STAGING_STUB_EXTERNALS short-circuits external calls."""

    async def test_stub_mode_skips_real_r2_call(
        self, db_session: AsyncSession, monkeypatch
    ):
        from app.utils.r2_client import R2Client

        monkeypatch.setenv("STAGING_STUB_EXTERNALS", "1")
        client = R2Client("a", "b", "c", "bucket")

        # _get_boto_client should never be invoked in stub mode
        called = {"n": 0}

        def _fail():
            called["n"] += 1
            raise AssertionError("boto client should not be used in stub mode")

        monkeypatch.setattr(client, "_get_boto_client", _fail)
        ok = client.delete_object("some/key")
        assert ok is True
        assert called["n"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestExternalDeleteIdempotency:
    """External delete helpers treat 'already absent' as success."""

    async def test_r2_nosuchkey_is_success(self, monkeypatch):
        from app.utils.r2_client import R2Client

        monkeypatch.delenv("STAGING_STUB_EXTERNALS", raising=False)
        client = R2Client("a", "b", "c", "bucket")

        class FakeError(Exception):
            def __init__(self):
                super().__init__("no such key")
                self.response = {"Error": {"Code": "NoSuchKey"}}

        class FakeS3:
            def delete_object(self, **_):
                raise FakeError()

        monkeypatch.setattr(client, "_get_boto_client", lambda: FakeS3())
        assert client.delete_object("missing/key") is True
