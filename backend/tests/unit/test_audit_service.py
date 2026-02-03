"""
Unit tests for AuditService.

Tests audit logging for various user actions and system events.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import AuditService
from app.models.audit_log import AuditLog


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServiceBasic:
    """Test basic audit logging operations."""

    async def test_log_basic(self, db_session: AsyncSession):
        """Test basic audit log creation."""
        service = AuditService(db_session)

        log = await service.log(
            action="TEST_ACTION",
            user_id=1,
            resource_type="USER",
            resource_id=2,
            details={"key": "value"},
            ip_address="192.168.1.1",
            user_agent="TestAgent/1.0"
        )

        assert log.id is not None
        assert log.action == "TEST_ACTION"
        assert log.user_id == 1
        assert log.resource_type == "USER"
        assert log.resource_id == 2
        assert log.details == {"key": "value"}
        assert log.ip_address == "192.168.1.1"
        assert log.user_agent == "TestAgent/1.0"


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServiceAuthentication:
    """Test authentication-related audit logs."""

    async def test_log_login_success(self, db_session: AsyncSession):
        """Test logging successful login."""
        service = AuditService(db_session)

        log = await service.log_login(
            user_id=1,
            ip_address="192.168.1.1",
            success=True
        )

        assert log.action == "LOGIN_SUCCESS"
        assert log.user_id == 1

    async def test_log_login_failed(self, db_session: AsyncSession):
        """Test logging failed login."""
        service = AuditService(db_session)

        log = await service.log_login(
            user_id=1,
            ip_address="192.168.1.1",
            success=False
        )

        assert log.action == "LOGIN_FAILED"
        assert log.user_id == 1

    async def test_log_logout(self, db_session: AsyncSession):
        """Test logging logout."""
        service = AuditService(db_session)

        log = await service.log_logout(
            user_id=1,
            ip_address="192.168.1.1"
        )

        assert log.action == "LOGOUT"
        assert log.user_id == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServiceUserManagement:
    """Test user management audit logs."""

    async def test_log_user_create(self, db_session: AsyncSession):
        """Test logging user creation."""
        service = AuditService(db_session)

        log = await service.log_user_create(
            user_id=1,
            created_user_id=2,
            details={"email": "new@test.com"}
        )

        assert log.action == "USER_CREATE"
        assert log.user_id == 1
        assert log.resource_type == "USER"
        assert log.resource_id == 2

    async def test_log_user_update(self, db_session: AsyncSession):
        """Test logging user update."""
        service = AuditService(db_session)

        changes = {"email": {"old": "old@test.com", "new": "new@test.com"}}
        log = await service.log_user_update(
            user_id=1,
            updated_user_id=2,
            changes=changes
        )

        assert log.action == "USER_UPDATE"
        assert log.details == {"changes": changes}

    async def test_log_user_delete(self, db_session: AsyncSession):
        """Test logging user deletion."""
        service = AuditService(db_session)

        log = await service.log_user_delete(
            user_id=1,
            deleted_user_id=2
        )

        assert log.action == "USER_DELETE"
        assert log.resource_id == 2

    async def test_log_role_change(self, db_session: AsyncSession):
        """Test logging role change."""
        service = AuditService(db_session)

        log = await service.log_role_change(
            user_id=1,
            target_user_id=2,
            old_role="invitee",
            new_role="sponsor"
        )

        assert log.action == "ROLE_CHANGE"
        assert log.details["old_role"] == "invitee"
        assert log.details["new_role"] == "sponsor"


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServicePasswordOps:
    """Test password-related audit logs."""

    async def test_log_password_reset(self, db_session: AsyncSession):
        """Test logging password reset by admin."""
        service = AuditService(db_session)

        log = await service.log_password_reset(
            user_id=1,
            target_user_id=2
        )

        assert log.action == "PASSWORD_RESET"
        assert log.user_id == 1
        assert log.resource_id == 2

    async def test_log_password_change(self, db_session: AsyncSession):
        """Test logging self-service password change."""
        service = AuditService(db_session)

        log = await service.log_password_change(user_id=1)

        assert log.action == "PASSWORD_CHANGE"
        assert log.user_id == 1
        assert log.resource_id == 1  # Same user

    async def test_log_password_reset_request(self, db_session: AsyncSession):
        """Test logging password reset request."""
        service = AuditService(db_session)

        log = await service.log_password_reset_request(user_id=1)

        assert log.action == "PASSWORD_RESET_REQUEST"
        assert log.user_id == 1

    async def test_log_password_reset_complete(self, db_session: AsyncSession):
        """Test logging password reset completion."""
        service = AuditService(db_session)

        log = await service.log_password_reset_complete(user_id=1)

        assert log.action == "PASSWORD_RESET_COMPLETE"
        assert log.user_id == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServiceBulkOps:
    """Test bulk operation audit logs."""

    async def test_log_bulk_action(self, db_session: AsyncSession):
        """Test logging bulk operations."""
        service = AuditService(db_session)

        affected_ids = [1, 2, 3, 4, 5]
        log = await service.log_bulk_action(
            user_id=1,
            action="activate",
            affected_user_ids=affected_ids
        )

        assert log.action == "BULK_ACTIVATE"
        assert log.details["count"] == 5
        assert log.details["affected_users"] == affected_ids


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServiceVPN:
    """Test VPN-related audit logs."""

    async def test_log_vpn_assignment(self, db_session: AsyncSession):
        """Test logging VPN assignment."""
        service = AuditService(db_session)

        log = await service.log_vpn_assignment(
            user_id=1,
            target_user_id=2,
            vpn_id=100
        )

        assert log.action == "VPN_ASSIGN"
        assert log.resource_type == "VPN"
        assert log.resource_id == 100
        assert log.details["assigned_to_user_id"] == 2

    async def test_log_vpn_unassignment(self, db_session: AsyncSession):
        """Test logging VPN unassignment."""
        service = AuditService(db_session)

        log = await service.log_vpn_unassignment(
            user_id=1,
            vpn_id=100
        )

        assert log.action == "VPN_UNASSIGN"
        assert log.resource_id == 100


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServiceEmail:
    """Test email-related audit logs."""

    async def test_log_email_send(self, db_session: AsyncSession):
        """Test logging email sending."""
        service = AuditService(db_session)

        recipient_ids = [1, 2, 3]
        log = await service.log_email_send(
            user_id=1,
            recipient_ids=recipient_ids,
            template_name="confirmation"
        )

        assert log.action == "EMAIL_SEND"
        assert log.resource_type == "EMAIL"
        assert log.details["template"] == "confirmation"
        assert log.details["count"] == 3


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServiceEvent:
    """Test event-related audit logs."""

    async def test_log_participation_confirm(self, db_session: AsyncSession):
        """Test logging participation confirmation."""
        service = AuditService(db_session)

        log = await service.log_participation_confirm(
            user_id=1,
            event_id=2026
        )

        assert log.action == "PARTICIPATION_CONFIRM"
        assert log.resource_type == "EVENT"
        assert log.resource_id == 2026

    async def test_log_terms_acceptance(self, db_session: AsyncSession):
        """Test logging terms acceptance."""
        service = AuditService(db_session)

        log = await service.log_terms_acceptance(
            user_id=1,
            event_id=2026,
            terms_version="v2.1"
        )

        assert log.action == "TERMS_ACCEPT"
        assert log.details["terms_version"] == "v2.1"

    async def test_log_event_create(self, db_session: AsyncSession):
        """Test logging event creation."""
        service = AuditService(db_session)

        log = await service.log_event_create(
            user_id=1,
            event_id=2026,
            details={"year": 2026}
        )

        assert log.action == "EVENT_CREATE"
        assert log.resource_id == 2026

    async def test_log_event_update(self, db_session: AsyncSession):
        """Test logging event update."""
        service = AuditService(db_session)

        changes = {"name": {"old": "Old Name", "new": "New Name"}}
        log = await service.log_event_update(
            user_id=1,
            event_id=2026,
            changes=changes
        )

        assert log.action == "EVENT_UPDATE"
        assert log.details["changes"] == changes

    async def test_log_event_activate(self, db_session: AsyncSession):
        """Test logging event activation."""
        service = AuditService(db_session)

        log = await service.log_event_activate(
            user_id=1,
            event_id=2026
        )

        assert log.action == "EVENT_ACTIVATE"
        assert log.details["action"] == "activate"

    async def test_log_event_archive(self, db_session: AsyncSession):
        """Test logging event archival."""
        service = AuditService(db_session)

        log = await service.log_event_archive(
            user_id=1,
            event_id=2025
        )

        assert log.action == "EVENT_ARCHIVE"
        assert log.details["action"] == "archive"


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServiceWorkflow:
    """Test workflow-related audit logs."""

    async def test_log_workflow_create(self, db_session: AsyncSession):
        """Test logging workflow creation."""
        service = AuditService(db_session)

        log = await service.log_workflow_create(
            user_id=1,
            workflow_id=10,
            details={"name": "test_workflow"}
        )

        assert log.action == "WORKFLOW_CREATE"
        assert log.resource_type == "WORKFLOW"

    async def test_log_workflow_update(self, db_session: AsyncSession):
        """Test logging workflow update."""
        service = AuditService(db_session)

        changes = {"is_enabled": {"old": False, "new": True}}
        log = await service.log_workflow_update(
            user_id=1,
            workflow_id=10,
            changes=changes
        )

        assert log.action == "WORKFLOW_UPDATE"
        assert log.details["changes"] == changes

    async def test_log_workflow_delete(self, db_session: AsyncSession):
        """Test logging workflow deletion."""
        service = AuditService(db_session)

        log = await service.log_workflow_delete(
            user_id=1,
            workflow_id=10
        )

        assert log.action == "WORKFLOW_DELETE"

    async def test_log_workflow_trigger(self, db_session: AsyncSession):
        """Test logging workflow trigger."""
        service = AuditService(db_session)

        log = await service.log_workflow_trigger(
            user_id=1,
            workflow_id=10,
            trigger_event="user_confirmed",
            details={"user_email": "test@test.com"}
        )

        assert log.action == "WORKFLOW_TRIGGER"
        assert log.details["trigger_event"] == "user_confirmed"
        assert log.details["user_email"] == "test@test.com"


@pytest.mark.unit
@pytest.mark.asyncio
class TestAuditServiceInvitation:
    """Test invitation-related audit logs."""

    async def test_log_invitation_blocked(self, db_session: AsyncSession):
        """Test logging blocked invitation."""
        service = AuditService(db_session)

        log = await service.log_invitation_blocked(
            user_id=1,
            target_user_id=2,
            reason="test_mode_restricted_non_sponsor",
            event_id=2026
        )

        assert log.action == "INVITATION_BLOCKED"
        assert log.details["reason"] == "test_mode_restricted_non_sponsor"
        assert log.details["event_id"] == 2026

    async def test_log_reminder_sent(self, db_session: AsyncSession):
        """Test logging invitation reminder."""
        service = AuditService(db_session)

        log = await service.log_reminder_sent(
            user_id=1,
            target_user_id=2,
            stage=1,
            event_id=2026,
            event_name="CyberX 2026",
            template_name="reminder_1",
            days_until_event=30
        )

        assert log.action == "REMINDER_1_SENT"
        assert log.details["stage"] == 1
        assert log.details["days_until_event"] == 30
        assert log.details["template"] == "reminder_1"
