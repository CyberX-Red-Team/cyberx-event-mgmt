"""Secrets are not stored in plaintext in audit details or finished emails."""
import copy
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.email_queue import EmailQueue, EmailQueueStatus
from app.models.user import User, UserRole
from app.services.audit_service import AuditService
from app.services.email_queue_service import EmailQueueService
from app.utils.redaction import REDACTED, SECRET_KEYS, redact_secrets


SECRET_VARS = {
    "first_name": "Ada",
    "pandas_username": "ada",
    "pandas_password": "hunter2",
    "password": "hunter2",
    "password_phonetic": "HOTEL uniform",
    "reset_token": "tok-abc",
    "reset_url": "https://x/reset-password?token=tok-abc",
}


# ── Helper ────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRedactSecrets:

    def test_masks_secret_keys_and_keeps_others(self):
        out = redact_secrets(SECRET_VARS)
        assert out["first_name"] == "Ada"
        assert out["pandas_username"] == "ada"
        for key in ("pandas_password", "password", "password_phonetic",
                    "reset_token", "reset_url"):
            assert out[key] == REDACTED

    def test_does_not_touch_lookalike_keys(self):
        data = {
            "tokens_used": 5, "total_tokens_generated": 9, "token_hash": "h",
            "ssh_public_key": "ssh-ed25519 AAAA", "password_email_sent": True,
            "has_password": False,
        }
        assert redact_secrets(data) == data

    def test_case_insensitive(self):
        assert redact_secrets({"Password": "x", "SSH_PRIVATE_KEY": "y"}) == {
            "Password": REDACTED, "SSH_PRIVATE_KEY": REDACTED,
        }

    def test_nested_change_entry_keeps_shape_and_nulls(self):
        # EVENT_UPDATE shape
        changes = {"changes": {
            "ssh_private_key": {"old": None, "new": "-----BEGIN KEY-----",
                                "old_value": None, "new_value": "-----BEGIN KEY-----"},
            "name": {"old": "A", "new": "B"},
        }}
        out = redact_secrets(changes)
        assert out["changes"]["ssh_private_key"] == {
            "old": None, "new": REDACTED, "old_value": None, "new_value": REDACTED,
        }
        assert out["changes"]["name"] == {"old": "A", "new": "B"}

    def test_lists_and_scalars(self):
        assert redact_secrets([{"password": "x"}, {"a": 1}]) == [{"password": REDACTED}, {"a": 1}]
        assert redact_secrets(None) is None
        assert redact_secrets("plain") == "plain"
        assert redact_secrets({"secret": None}) == {"secret": None}

    def test_never_mutates_input(self):
        original = {"changes": {"pandas_password": "hunter2", "nested": [{"secret": "s"}]}}
        snapshot = copy.deepcopy(original)
        redact_secrets(original)
        assert original == snapshot


# ── Audit log ─────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditLogRedaction:

    async def test_service_write_is_redacted_in_the_database(self, db_session):
        changes = {"email": "a@b.c", "pandas_password": "hunter2"}
        await AuditService(db_session).log(
            action="USER_UPDATE", details={"changes": changes},
        )
        # Caller's dict is untouched (routes keep using it after logging).
        assert changes["pandas_password"] == "hunter2"

        db_session.expire_all()
        row = (await db_session.execute(select(AuditLog))).scalar_one()
        assert row.details == {"changes": {"email": "a@b.c", "pandas_password": REDACTED}}

    async def test_direct_construction_is_redacted(self, db_session):
        # vpn.py builds AuditLog() directly, bypassing AuditService.
        db_session.add(AuditLog(action="VPN_REQUEST", details={"private_key": "k", "count": 1}))
        await db_session.commit()
        db_session.expire_all()
        row = (await db_session.execute(select(AuditLog))).scalar_one()
        assert row.details == {"private_key": REDACTED, "count": 1}

    async def test_reassignment_is_redacted(self, db_session):
        log = AuditLog(action="X", details={})
        log.details = {"secret": "s"}
        assert log.details == {"secret": REDACTED}

    async def test_non_secret_details_unchanged(self, db_session):
        details = {"client_id": "abc", "count": 3, "nested": {"ok": [1, 2]}}
        log = await AuditService(db_session).log(action="X", details=details)
        assert log.details == details


# ── Email queue ───────────────────────────────────────────────────────────

@pytest.fixture
async def user(db_session):
    u = User(
        email="ada@test.com", first_name="Ada", last_name="L", country="USA",
        role=UserRole.INVITEE.value, is_active=True,
    )
    db_session.add(u)
    await db_session.commit()
    return u


async def _reload(db_session, email_id):
    db_session.expire_all()
    return (await db_session.execute(
        select(EmailQueue).where(EmailQueue.id == email_id)
    )).scalar_one()


@pytest.mark.unit
@pytest.mark.asyncio
class TestEmailQueueScrub:

    async def _enqueue(self, db_session, user, **kw):
        return await EmailQueueService(db_session).enqueue_email(
            user.id, "credentials", custom_vars=dict(SECRET_VARS), **kw,
        )

    async def test_sent_email_is_scrubbed_but_sender_got_the_real_vars(
        self, db_session, user, mocker,
    ):
        email = await self._enqueue(db_session, user)
        send = mocker.patch(
            "app.services.email_queue_service.EmailService.send_email",
            return_value=(True, "ok", "msg-1"),
        )
        await EmailQueueService(db_session).process_batch(batch_size=10)

        # The email went out with the real password...
        assert send.call_args.kwargs["custom_vars"]["password"] == "hunter2"
        # ...and only a redacted copy is kept.
        row = await _reload(db_session, email.id)
        assert row.status == EmailQueueStatus.SENT
        assert row.custom_vars["password"] == REDACTED
        assert row.custom_vars["reset_url"] == REDACTED
        assert row.custom_vars["first_name"] == "Ada"

    async def test_failure_with_retries_left_keeps_vars_for_the_retry(
        self, db_session, user, mocker,
    ):
        email = await self._enqueue(db_session, user)
        mocker.patch(
            "app.services.email_queue_service.EmailService.send_email",
            return_value=(False, "temporary", None),
        )
        await EmailQueueService(db_session).process_batch(batch_size=10)

        row = await _reload(db_session, email.id)
        assert row.status == EmailQueueStatus.PENDING
        assert row.custom_vars["password"] == "hunter2"

    async def test_final_failure_is_scrubbed(self, db_session, user, mocker):
        email = await self._enqueue(db_session, user)
        email.attempts = email.max_attempts - 1
        await db_session.commit()
        mocker.patch(
            "app.services.email_queue_service.EmailService.send_email",
            return_value=(False, "bounced", None),
        )
        await EmailQueueService(db_session).process_batch(batch_size=10)

        row = await _reload(db_session, email.id)
        assert row.status == EmailQueueStatus.FAILED
        assert row.custom_vars["password"] == REDACTED

    async def test_final_exception_is_scrubbed(self, db_session, user, mocker):
        email = await self._enqueue(db_session, user)
        email.attempts = email.max_attempts - 1
        await db_session.commit()
        mocker.patch(
            "app.services.email_queue_service.EmailService.send_email",
            side_effect=RuntimeError("boom"),
        )
        await EmailQueueService(db_session).process_batch(batch_size=10)

        row = await _reload(db_session, email.id)
        assert row.status == EmailQueueStatus.FAILED
        assert row.custom_vars["password"] == REDACTED

    async def test_exception_with_retries_left_keeps_vars(self, db_session, user, mocker):
        email = await self._enqueue(db_session, user)
        mocker.patch(
            "app.services.email_queue_service.EmailService.send_email",
            side_effect=RuntimeError("boom"),
        )
        await EmailQueueService(db_session).process_batch(batch_size=10)

        row = await _reload(db_session, email.id)
        assert row.status == EmailQueueStatus.PENDING
        assert row.custom_vars["password"] == "hunter2"

    async def test_cancel_is_scrubbed(self, db_session, user):
        email = await self._enqueue(db_session, user)
        assert await EmailQueueService(db_session).cancel_email(email.id)
        row = await _reload(db_session, email.id)
        assert row.status == EmailQueueStatus.CANCELLED
        assert row.custom_vars["password"] == REDACTED

    async def test_bulk_cancel_is_scrubbed(self, db_session, user):
        email = await self._enqueue(db_session, user)
        count, _ = await EmailQueueService(db_session).bulk_cancel_emails([email.id])
        assert count == 1
        row = await _reload(db_session, email.id)
        assert row.custom_vars["password"] == REDACTED

    async def test_pending_email_is_untouched(self, db_session, user):
        email = await self._enqueue(db_session, user)
        row = await _reload(db_session, email.id)
        assert row.custom_vars == SECRET_VARS


# ── Migration ─────────────────────────────────────────────────────────────

def _load_migration():
    path = (Path(__file__).resolve().parents[2] / "migrations" / "versions"
            / "20261119_000000_redact_secrets_at_rest.py")
    spec = importlib.util.spec_from_file_location("redact_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
class TestRedactMigration:

    @pytest.fixture
    def conn(self):
        engine = sa.create_engine("sqlite://")
        md = sa.MetaData()
        sa.Table("audit_logs", md,
                 sa.Column("id", sa.Integer, primary_key=True),
                 sa.Column("details", sa.JSON))
        sa.Table("email_queue", md,
                 sa.Column("id", sa.Integer, primary_key=True),
                 sa.Column("status", sa.String(20)),
                 sa.Column("custom_vars", sa.JSON))
        md.create_all(engine)
        with engine.begin() as c:
            yield c, md

    def test_frozen_key_list_matches_the_app(self):
        assert _load_migration().SECRET_KEYS == SECRET_KEYS

    def test_upgrade_scrubs_existing_rows_and_is_idempotent(self, conn, monkeypatch):
        c, md = conn
        audit, email = md.tables["audit_logs"], md.tables["email_queue"]
        c.execute(audit.insert(), [
            {"id": 1, "details": {"changes": {"pandas_password": "hunter2", "email": "e"}}},
            {"id": 2, "details": {"changes": {"ssh_private_key": {"old": "K1", "new": "K2"}}}},
            {"id": 3, "details": {"tokens_used": 4}},
            {"id": 4, "details": None},
        ])
        c.execute(email.insert(), [
            {"id": 1, "status": "sent", "custom_vars": dict(SECRET_VARS)},
            {"id": 2, "status": "failed", "custom_vars": {"password": "p"}},
            {"id": 3, "status": "cancelled", "custom_vars": {"reset_token": "t"}},
            {"id": 4, "status": "pending", "custom_vars": {"password": "keep-me"}},
            {"id": 5, "status": "processing", "custom_vars": {"password": "keep-me"}},
            {"id": 6, "status": "sent", "custom_vars": None},
        ])

        migration = _load_migration()
        monkeypatch.setattr(migration.op, "get_bind", lambda: c, raising=False)
        migration.upgrade()

        details = dict(c.execute(sa.select(audit.c.id, audit.c.details)).fetchall())
        assert details[1] == {"changes": {"pandas_password": REDACTED, "email": "e"}}
        assert details[2] == {"changes": {"ssh_private_key": {"old": REDACTED, "new": REDACTED}}}
        assert details[3] == {"tokens_used": 4}
        assert details[4] is None

        vars_ = dict(c.execute(sa.select(email.c.id, email.c.custom_vars)).fetchall())
        assert vars_[1]["password"] == REDACTED and vars_[1]["first_name"] == "Ada"
        assert vars_[2] == {"password": REDACTED}
        assert vars_[3] == {"reset_token": REDACTED}
        assert vars_[4] == {"password": "keep-me"}   # not finished: still needed
        assert vars_[5] == {"password": "keep-me"}
        assert vars_[6] is None

        # Re-running changes nothing.
        assert migration._scrub(c, audit, audit.c.details) == 0
        assert migration._scrub(
            c, email, email.c.custom_vars,
            where=email.c.status.in_(migration.FINISHED_EMAIL_STATUSES),
        ) == 0

    def test_scrub_pages_through_more_than_one_batch(self, conn, monkeypatch):
        c, md = conn
        audit = md.tables["audit_logs"]
        migration = _load_migration()
        monkeypatch.setattr(migration, "BATCH", 3)
        c.execute(audit.insert(), [{"id": i, "details": {"secret": str(i)}} for i in range(1, 11)])
        assert migration._scrub(c, audit, audit.c.details) == 10
        rows = c.execute(sa.select(audit.c.details)).scalars().all()
        assert all(r == {"secret": REDACTED} for r in rows)
