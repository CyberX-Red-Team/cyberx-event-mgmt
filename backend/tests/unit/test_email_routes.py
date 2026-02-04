"""Unit tests for email API routes.

Tests route-level logic, validation, error handling, and response formatting.
All service dependencies are mocked to isolate route behavior.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock

from app.api.routes.email import (
    send_email,
    send_vpn_config_email,
    send_bulk_emails,
    send_test_email
)
from app.schemas.email import (
    SendEmailRequest,
    BulkEmailRequest,
    SendCustomEmailRequest,
    SendTestEmailRequest
)
from app.models.user import User, UserRole


@pytest.mark.unit
@pytest.mark.asyncio
class TestSendEmailRoute:
    """Test POST /api/email/send endpoint."""

    async def test_send_email_participant_not_found(self, mocker):
        """Test sending email when participant doesn't exist."""
        mock_request = mocker.Mock()
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = SendEmailRequest(
            participant_id=999,
            template_id=1
        )

        mock_participant_service = mocker.Mock()
        mock_participant_service.get_participant = mocker.AsyncMock(return_value=None)

        mock_email_service = mocker.Mock()
        mock_audit_service = mocker.Mock()

        with pytest.raises(Exception):
            await send_email(
                data=data,
                request=mock_request,
                current_user=mock_user,
                email_service=mock_email_service,
                participant_service=mock_participant_service,
                audit_service=mock_audit_service
            )

    async def test_send_email_template_not_found(self, mocker):
        """Test sending email when template doesn't exist."""
        mock_request = mocker.Mock()
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = SendEmailRequest(
            participant_id=1,
            template_id=999
        )

        mock_participant = Mock(id=1, email="user@test.com")

        mock_participant_service = mocker.Mock()
        mock_participant_service.get_participant = mocker.AsyncMock(return_value=mock_participant)

        mock_email_service = mocker.Mock()
        mock_email_service.get_template_by_id = mocker.AsyncMock(return_value=None)

        mock_audit_service = mocker.Mock()

        with pytest.raises(Exception):
            await send_email(
                data=data,
                request=mock_request,
                current_user=mock_user,
                email_service=mock_email_service,
                participant_service=mock_participant_service,
                audit_service=mock_audit_service
            )

    async def test_send_email_template_inactive(self, mocker):
        """Test sending email when template is inactive."""
        mock_request = mocker.Mock()
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = SendEmailRequest(
            participant_id=1,
            template_id=1
        )

        mock_participant = Mock(id=1, email="user@test.com")
        mock_template = Mock(id=1, name="test_template", is_active=False)

        mock_participant_service = mocker.Mock()
        mock_participant_service.get_participant = mocker.AsyncMock(return_value=mock_participant)

        mock_email_service = mocker.Mock()
        mock_email_service.get_template_by_id = mocker.AsyncMock(return_value=mock_template)

        mock_audit_service = mocker.Mock()

        with pytest.raises(Exception):
            await send_email(
                data=data,
                request=mock_request,
                current_user=mock_user,
                email_service=mock_email_service,
                participant_service=mock_participant_service,
                audit_service=mock_audit_service
            )

    async def test_send_email_success(self, mocker):
        """Test successfully sending email."""
        mock_request = mocker.Mock()
        mock_request.client = mocker.Mock(host="192.168.1.1")
        mock_request.headers = {"user-agent": "TestBrowser"}

        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = SendEmailRequest(
            participant_id=1,
            template_id=1,
            custom_subject="Test Subject",
            custom_variables={"name": "Test"}
        )

        mock_participant = Mock(id=1, email="user@test.com")
        mock_template = Mock(id=1, name="test_template", is_active=True)

        mock_participant_service = mocker.Mock()
        mock_participant_service.get_participant = mocker.AsyncMock(return_value=mock_participant)

        mock_email_service = mocker.Mock()
        mock_email_service.get_template_by_id = mocker.AsyncMock(return_value=mock_template)
        mock_email_service.send_email_with_template_id = mocker.AsyncMock(
            return_value=(True, "Email sent", "msg_123")
        )

        mock_audit_service = mocker.Mock()
        mock_audit_service.log_email_send = mocker.AsyncMock()

        result = await send_email(
            data=data,
            request=mock_request,
            current_user=mock_user,
            email_service=mock_email_service,
            participant_service=mock_participant_service,
            audit_service=mock_audit_service
        )

        assert result.success is True
        assert result.message == "Email sent"
        assert result.message_id == "msg_123"
        assert result.recipient_email == "user@test.com"


@pytest.mark.unit
@pytest.mark.asyncio
class TestSendVPNConfigEmailRoute:
    """Test POST /api/email/send-vpn-config endpoint."""

    async def test_send_vpn_config_participant_not_found(self, mocker):
        """Test sending VPN config when participant doesn't exist."""
        mock_request = mocker.Mock()
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        mock_participant_service = mocker.Mock()
        mock_participant_service.get_participant = mocker.AsyncMock(return_value=None)

        mock_email_service = mocker.Mock()
        mock_vpn_service = mocker.Mock()
        mock_audit_service = mocker.Mock()

        with pytest.raises(Exception):
            await send_vpn_config_email(
                participant_id=999,
                request=mock_request,
                current_user=mock_user,
                email_service=mock_email_service,
                participant_service=mock_participant_service,
                vpn_service=mock_vpn_service,
                audit_service=mock_audit_service
            )

    async def test_send_vpn_config_no_vpn_assigned(self, mocker):
        """Test sending VPN config when participant has no VPN."""
        mock_request = mocker.Mock()
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        mock_participant = Mock(id=1, email="user@test.com")

        mock_participant_service = mocker.Mock()
        mock_participant_service.get_participant = mocker.AsyncMock(return_value=mock_participant)

        mock_vpn_service = mocker.Mock()
        mock_vpn_service.get_user_credential = mocker.AsyncMock(return_value=None)

        mock_email_service = mocker.Mock()
        mock_audit_service = mocker.Mock()

        with pytest.raises(Exception):
            await send_vpn_config_email(
                participant_id=1,
                request=mock_request,
                current_user=mock_user,
                email_service=mock_email_service,
                participant_service=mock_participant_service,
                vpn_service=mock_vpn_service,
                audit_service=mock_audit_service
            )

    async def test_send_vpn_config_success(self, mocker):
        """Test successfully sending VPN config email."""
        mock_request = mocker.Mock()
        mock_request.client = mocker.Mock(host="192.168.1.1")
        mock_request.headers = {"user-agent": "TestBrowser"}

        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        mock_participant = Mock(id=1, email="user@test.com", first_name="Test", last_name="User")
        mock_vpn = Mock(id=1, user_id=1)

        mock_participant_service = mocker.Mock()
        mock_participant_service.get_participant = mocker.AsyncMock(return_value=mock_participant)

        mock_vpn_service = mocker.Mock()
        mock_vpn_service.get_user_credential = mocker.AsyncMock(return_value=mock_vpn)
        mock_vpn_service.generate_wireguard_config = mocker.Mock(return_value="[Interface]\n...")
        mock_vpn_service.get_config_filename = mocker.Mock(return_value="test_user.conf")

        mock_email_service = mocker.Mock()
        mock_email_service.send_email = mocker.AsyncMock(
            return_value=(True, "VPN config sent", "msg_456")
        )

        mock_audit_service = mocker.Mock()
        mock_audit_service.log_email_send = mocker.AsyncMock()

        result = await send_vpn_config_email(
            participant_id=1,
            request=mock_request,
            current_user=mock_user,
            email_service=mock_email_service,
            participant_service=mock_participant_service,
            vpn_service=mock_vpn_service,
            audit_service=mock_audit_service
        )

        assert result.success is True
        assert result.message == "VPN config sent"
        assert result.message_id == "msg_456"


@pytest.mark.unit
@pytest.mark.asyncio
class TestBulkEmailRoute:
    """Test POST /api/email/bulk endpoint."""

    async def test_bulk_email_template_not_found(self, mocker):
        """Test bulk email when template doesn't exist."""
        mock_request = mocker.Mock()
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = BulkEmailRequest(
            participant_ids=[1, 2, 3],
            template_id=999
        )

        mock_email_service = mocker.Mock()
        mock_email_service.get_template_by_id = mocker.AsyncMock(return_value=None)

        mock_participant_service = mocker.Mock()
        mock_audit_service = mocker.Mock()
        mock_db = mocker.AsyncMock()

        with pytest.raises(Exception):
            await send_bulk_emails(
                data=data,
                request=mock_request,
                current_user=mock_user,
                email_service=mock_email_service,
                participant_service=mock_participant_service,
                audit_service=mock_audit_service,
                db=mock_db
            )

    async def test_bulk_email_template_inactive(self, mocker):
        """Test bulk email when template is inactive."""
        mock_request = mocker.Mock()
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = BulkEmailRequest(
            participant_ids=[1, 2, 3],
            template_id=1
        )

        mock_template = Mock(id=1, name="test_template", is_active=False)

        mock_email_service = mocker.Mock()
        mock_email_service.get_template_by_id = mocker.AsyncMock(return_value=mock_template)

        mock_participant_service = mocker.Mock()
        mock_audit_service = mocker.Mock()
        mock_db = mocker.AsyncMock()

        with pytest.raises(Exception):
            await send_bulk_emails(
                data=data,
                request=mock_request,
                current_user=mock_user,
                email_service=mock_email_service,
                participant_service=mock_participant_service,
                audit_service=mock_audit_service,
                db=mock_db
            )

    async def test_bulk_email_no_valid_participants(self, mocker):
        """Test bulk email when no valid participants found."""
        mock_request = mocker.Mock()
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = BulkEmailRequest(
            participant_ids=[999, 998, 997],
            template_id=1
        )

        mock_template = Mock(id=1, name="test_template", is_active=True)

        mock_email_service = mocker.Mock()
        mock_email_service.get_template_by_id = mocker.AsyncMock(return_value=mock_template)

        mock_participant_service = mocker.Mock()
        mock_participant_service.get_participant = mocker.AsyncMock(return_value=None)

        mock_audit_service = mocker.Mock()
        mock_db = mocker.AsyncMock()

        with pytest.raises(Exception):
            await send_bulk_emails(
                data=data,
                request=mock_request,
                current_user=mock_user,
                email_service=mock_email_service,
                participant_service=mock_participant_service,
                audit_service=mock_audit_service,
                db=mock_db
            )


@pytest.mark.unit
@pytest.mark.asyncio
class TestTestEmailRoute:
    """Test POST /api/email/test endpoint."""

    async def test_send_test_email_template_not_found(self, mocker):
        """Test sending test email when template doesn't exist."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = SendTestEmailRequest(
            to_email="test@test.com",
            template_id=999
        )

        mock_email_service = mocker.Mock()
        mock_email_service.send_test_email = mocker.AsyncMock(
            return_value=(False, "Template not found", None, None)
        )

        result = await send_test_email(
            data=data,
            current_user=mock_user,
            email_service=mock_email_service
        )

        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_send_test_email_template_inactive(self, mocker):
        """Test sending test email when template is inactive."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = SendTestEmailRequest(
            to_email="test@test.com",
            template_id=1
        )

        mock_email_service = mocker.Mock()
        mock_email_service.send_test_email = mocker.AsyncMock(
            return_value=(False, "Template is inactive", None, None)
        )

        result = await send_test_email(
            data=data,
            current_user=mock_user,
            email_service=mock_email_service
        )

        assert result.success is False
        assert "inactive" in result.message.lower()

    async def test_send_test_email_success(self, mocker):
        """Test successfully sending test email."""
        mock_user = User(
            id=1,
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        data = SendTestEmailRequest(
            to_email="test@test.com",
            template_id=1,
            subject="Test Email Subject"
        )

        mock_email_service = mocker.Mock()
        mock_email_service.send_test_email = mocker.AsyncMock(
            return_value=(True, "Test email sent", "msg_789", "test_template")
        )

        result = await send_test_email(
            data=data,
            current_user=mock_user,
            email_service=mock_email_service
        )

        assert result.success is True
        assert result.message == "Test email sent"
        assert result.message_id == "msg_789"
        assert result.to_email == "test@test.com"
        assert result.template_used == "test_template"
