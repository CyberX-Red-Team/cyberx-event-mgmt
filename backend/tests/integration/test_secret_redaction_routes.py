"""Real admin routes still apply secrets, but never store them in the audit log."""
import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.email_queue import EmailQueue, EmailQueueStatus
from app.models.event import Event
from app.models.user import User
from app.utils.redaction import REDACTED


pytestmark = [pytest.mark.integration]


async def _audit(db_session, action):
    db_session.expire_all()
    return (await db_session.execute(
        select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id.desc())
    )).scalars().first()


@pytest.mark.asyncio
class TestSecretRedactionThroughRoutes:

    async def test_participant_password_update_applies_but_audit_is_redacted(
        self, authenticated_admin_client, db_session, invitee_user,
    ):
        response = await authenticated_admin_client.put(
            f"/api/admin/participants/{invitee_user.id}",
            json={"pandas_password": "N3w-Secret-Pass!", "first_name": "Renamed"},
        )
        assert response.status_code == 200, response.text

        db_session.expire_all()
        user = (await db_session.execute(
            select(User).where(User.id == invitee_user.id)
        )).scalar_one()
        assert user.pandas_password == "N3w-Secret-Pass!"   # still applied
        assert user.first_name == "Renamed"

        entry = await _audit(db_session, "USER_UPDATE")
        assert entry is not None
        assert entry.details["changes"]["pandas_password"] == REDACTED
        assert entry.details["changes"]["first_name"] == "Renamed"
        assert "N3w-Secret-Pass!" not in str(entry.details)

    async def test_event_ssh_key_update_applies_but_audit_is_redacted(
        self, authenticated_admin_client, db_session, active_event,
    ):
        key = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"
        response = await authenticated_admin_client.put(
            f"/api/admin/events/{active_event.id}",
            json={"ssh_private_key": key, "ssh_public_key": "ssh-ed25519 AAAAtest",
                  "event_location": "Annapolis"},
        )
        assert response.status_code == 200, response.text

        db_session.expire_all()
        event = (await db_session.execute(
            select(Event).where(Event.id == active_event.id)
        )).scalar_one()
        assert event.ssh_private_key == key                  # still applied
        assert event.event_location == "Annapolis"

        entry = await _audit(db_session, "EVENT_UPDATE")
        changes = entry.details["changes"]
        assert changes["ssh_private_key"]["new"] == REDACTED
        assert changes["ssh_private_key"]["new_value"] == REDACTED
        assert changes["ssh_public_key"]["new"] == "ssh-ed25519 AAAAtest"  # public key kept
        assert changes["event_location"]["new"] == "Annapolis"
        assert "OPENSSH PRIVATE KEY" not in str(entry.details)

    async def test_deleting_a_participant_clears_their_pending_email_vars(
        self, authenticated_admin_client, db_session, invitee_user,
    ):
        email = EmailQueue(
            user_id=invitee_user.id, template_name="credentials",
            recipient_email=invitee_user.email,
            custom_vars={"password": "hunter2", "first_name": "Ada"},
            status=EmailQueueStatus.PENDING,
        )
        db_session.add(email)
        await db_session.commit()
        email_id = email.id

        response = await authenticated_admin_client.delete(
            f"/api/admin/participants/{invitee_user.id}"
        )
        assert response.status_code == 200, response.text

        db_session.expire_all()
        # email_queue.user_id is ON DELETE SET NULL, so the row survives.
        row = (await db_session.execute(
            select(EmailQueue).where(EmailQueue.id == email_id)
        )).scalar_one()
        assert row.status == EmailQueueStatus.CANCELLED
        assert row.custom_vars is None
