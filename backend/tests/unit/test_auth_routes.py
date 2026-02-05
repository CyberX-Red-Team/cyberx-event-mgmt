"""Unit tests for authentication API routes.

Tests route-level logic, validation, error handling, and response formatting.
All service dependencies are mocked to isolate route behavior.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.api.routes.auth import (
    check_login_rate_limit,
    clear_login_rate_limit,
    login,
    logout,
    get_current_user_info,
    change_password,
    request_password_reset,
    complete_password_reset,
    _login_rate_limit_cache
)
from app.schemas.auth import LoginRequest, PasswordChangeRequest, PasswordResetRequestSchema, PasswordResetCompleteSchema
from app.models.user import User, UserRole
from app.models.session import Session


@pytest.mark.unit
class TestRateLimiting:
    """Test rate limiting utility functions."""

    def setup_method(self):
        """Clear rate limit cache before each test."""
        _login_rate_limit_cache.clear()

    def test_check_login_rate_limit_first_attempt(self):
        """Test rate limiting allows first attempt."""
        result = check_login_rate_limit("192.168.1.1")

        assert result is False  # Not rate limited
        assert len(_login_rate_limit_cache["login_192.168.1.1"]) == 1

    def test_check_login_rate_limit_within_threshold(self):
        """Test rate limiting allows attempts within threshold."""
        ip = "192.168.1.2"

        # Make 4 attempts
        for _ in range(4):
            result = check_login_rate_limit(ip)
            assert result is False

        # 5th attempt should still be allowed (limit is 5)
        result = check_login_rate_limit(ip)
        assert result is False

    def test_check_login_rate_limit_exceeds_threshold(self):
        """Test rate limiting blocks after max attempts."""
        ip = "192.168.1.3"

        # Make 5 attempts (fill the limit)
        for _ in range(5):
            check_login_rate_limit(ip)

        # 6th attempt should be blocked
        result = check_login_rate_limit(ip)
        assert result is True

    def test_check_login_rate_limit_cleans_old_entries(self):
        """Test rate limiting cleans old entries outside time window."""
        ip = "192.168.1.4"
        cache_key = f"login_{ip}"

        # Add old timestamps (16 minutes ago)
        old_time = datetime.now(timezone.utc) - timedelta(minutes=16)
        _login_rate_limit_cache[cache_key] = [old_time] * 5

        # New attempt should be allowed (old entries cleaned)
        result = check_login_rate_limit(ip)
        assert result is False
        assert len(_login_rate_limit_cache[cache_key]) == 1  # Only new entry

    def test_clear_login_rate_limit_existing_key(self):
        """Test clearing rate limit for existing IP."""
        ip = "192.168.1.5"
        cache_key = f"login_{ip}"

        # Add some entries
        _login_rate_limit_cache[cache_key] = [datetime.now(timezone.utc)]

        # Clear rate limit
        clear_login_rate_limit(ip)

        assert cache_key not in _login_rate_limit_cache

    def test_clear_login_rate_limit_nonexistent_key(self):
        """Test clearing rate limit for non-existent IP doesn't error."""
        clear_login_rate_limit("192.168.1.6")
        # Should not raise error


@pytest.mark.unit
@pytest.mark.asyncio
class TestLoginRoute:
    """Test login route."""

    async def test_login_rate_limit_exceeded(self, mocker):
        """Test login fails when rate limit exceeded."""
        # Mock dependencies
        mock_request = mocker.Mock(spec=Request)
        mock_response = mocker.Mock(spec=Response)
        mock_auth_service = mocker.Mock()
        mock_db = mocker.AsyncMock()

        # Mock extract_client_metadata
        mocker.patch(
            'app.api.routes.auth.extract_client_metadata',
            return_value=("192.168.1.1", "TestAgent")
        )

        # Mock rate limit check to return True (exceeded)
        mocker.patch(
            'app.api.routes.auth.check_login_rate_limit',
            return_value=True
        )

        # Mock AuditService
        mock_audit = mocker.Mock()
        mock_audit.log_login = mocker.AsyncMock()
        mocker.patch('app.api.routes.auth.AuditService', return_value=mock_audit)

        login_data = LoginRequest(username="test@example.com", password="password")

        # Should raise rate_limited exception
        with pytest.raises(Exception) as exc_info:
            await login(login_data, mock_request, mock_response, mock_auth_service, mock_db)

        # Verify audit log was called
        mock_audit.log_login.assert_called_once()
        call_kwargs = mock_audit.log_login.call_args[1]
        assert call_kwargs['success'] is False
        assert call_kwargs['details']['reason'] == "Rate limit exceeded"

    async def test_login_invalid_credentials(self, mocker):
        """Test login fails with invalid credentials."""
        mock_request = mocker.Mock(spec=Request)
        mock_response = mocker.Mock(spec=Response)
        mock_auth_service = mocker.Mock()
        mock_auth_service.authenticate_user = mocker.AsyncMock(return_value=None)
        mock_db = mocker.AsyncMock()

        mocker.patch(
            'app.api.routes.auth.extract_client_metadata',
            return_value=("192.168.1.1", "TestAgent")
        )
        mocker.patch('app.api.routes.auth.check_login_rate_limit', return_value=False)

        mock_audit = mocker.Mock()
        mock_audit.log_login = mocker.AsyncMock()
        mocker.patch('app.api.routes.auth.AuditService', return_value=mock_audit)

        login_data = LoginRequest(username="test@example.com", password="wrongpass")

        with pytest.raises(Exception) as exc_info:
            await login(login_data, mock_request, mock_response, mock_auth_service, mock_db)

        # Verify audit log
        mock_audit.log_login.assert_called_once()
        call_kwargs = mock_audit.log_login.call_args[1]
        assert call_kwargs['success'] is False
        assert call_kwargs['details']['reason'] == "Invalid credentials"

    async def test_login_successful(self, mocker):
        """Test successful login flow."""
        mock_request = mocker.Mock(spec=Request)
        mock_response = mocker.Mock(spec=Response)
        mock_response.set_cookie = mocker.Mock()

        # Create mock user
        mock_user = User(
            id=1,
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        mock_auth_service = mocker.Mock()
        mock_auth_service.authenticate_user = mocker.AsyncMock(return_value=mock_user)
        mock_auth_service.create_session = mocker.AsyncMock(
            return_value=("test_session_token", datetime.now(timezone.utc) + timedelta(hours=24))
        )

        mock_db = mocker.AsyncMock()

        mocker.patch('app.api.routes.auth.extract_client_metadata', return_value=("192.168.1.1", "TestAgent"))
        mocker.patch('app.api.routes.auth.check_login_rate_limit', return_value=False)
        mocker.patch('app.api.routes.auth.clear_login_rate_limit')

        mock_audit = mocker.Mock()
        mock_audit.log_login = mocker.AsyncMock()
        mocker.patch('app.api.routes.auth.AuditService', return_value=mock_audit)

        # Mock build_auth_user_response
        mock_user_response = {
            "id": 1,
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "role": "admin",
            "is_admin": True,
            "country": "USA",
            "is_active": True,
            "confirmed": "YES",
            "email_status": "",
            "theme_preference": "light",
            "vpn_credentials": None
        }
        mocker.patch('app.api.routes.auth.build_auth_user_response', return_value=mock_user_response)

        login_data = LoginRequest(username="test@example.com", password="correct")

        result = await login(login_data, mock_request, mock_response, mock_auth_service, mock_db)

        # Verify response
        assert result.message == "Login successful"
        # Verify key user fields (build_auth_user_response returns a Pydantic model)
        assert result.user.id == 1
        assert result.user.email == "test@example.com"
        assert result.user.first_name == "Test"
        assert result.user.last_name == "User"

        # Verify cookie was set
        mock_response.set_cookie.assert_called_once()

        # Verify successful audit log
        assert mock_audit.log_login.call_count == 1
        call_kwargs = mock_audit.log_login.call_args[1]
        assert call_kwargs['success'] is True


@pytest.mark.unit
@pytest.mark.asyncio
class TestLogoutRoute:
    """Test logout route."""

    async def test_logout_successful(self, mocker):
        """Test successful logout."""
        mock_request = mocker.Mock(spec=Request)
        mock_response = mocker.Mock(spec=Response)
        mock_response.delete_cookie = mocker.Mock()

        session_token = "test_session_token"
        mock_auth_service = mocker.Mock()
        mock_auth_service.invalidate_session = mocker.AsyncMock()

        mock_db = mocker.AsyncMock()

        mock_user = User(
            id=1,
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value
        )

        mocker.patch('app.api.routes.auth.extract_client_metadata', return_value=("192.168.1.1", "TestAgent"))

        mock_audit = mocker.Mock()
        mock_audit.log_logout = mocker.AsyncMock()
        mocker.patch('app.api.routes.auth.AuditService', return_value=mock_audit)

        result = await logout(mock_request, mock_response, session_token, mock_auth_service, mock_db, mock_user)

        # Verify response
        assert result.message == "Logout successful"

        # Verify session invalidated
        mock_auth_service.invalidate_session.assert_called_once_with(session_token)

        # Verify cookie deleted
        mock_response.delete_cookie.assert_called_once()

        # Verify audit log
        mock_audit.log_logout.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetMeRoute:
    """Test /me route."""

    async def test_get_me_with_session(self, mocker):
        """Test get current user info with valid session."""
        mock_user = User(
            id=1,
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True
        )

        session_token = "test_token"

        mock_session = Session(
            id=1,
            session_token=session_token,
            user_id=1,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            is_active=True
        )

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_session
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        mock_user_response = {
            "id": 1,
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "role": "admin",
            "is_admin": True,
            "country": "USA",
            "is_active": True,
            "confirmed": "YES",
            "email_status": "",
            "theme_preference": "light",
            "vpn_credentials": None
        }
        mocker.patch('app.api.routes.auth.build_auth_user_response', return_value=mock_user_response)

        result = await get_current_user_info(mock_user, session_token, mock_db)

        # Verify key user fields (build_auth_user_response returns a Pydantic model)
        assert result.user.id == 1
        assert result.user.email == "test@example.com"
        assert result.user.first_name == "Test"
        assert result.user.last_name == "User"
        assert result.is_admin is True
        assert result.expires_at == mock_session.expires_at


@pytest.mark.unit
@pytest.mark.asyncio
class TestPasswordChangeRoute:
    """Test password change route."""

    async def test_password_change_invalid_current_password(self, mocker):
        """Test password change fails with incorrect current password."""
        mock_request = mocker.Mock(spec=Request)

        mock_user = User(
            id=1,
            email="test@example.com",
            pandas_username="testuser",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value
        )

        mock_auth_service = mocker.Mock()
        mock_auth_service.authenticate_user = mocker.AsyncMock(return_value=None)

        mock_db = mocker.AsyncMock()

        data = PasswordChangeRequest(
            current_password="wrongpass",
            new_password="newpass123"
        )

        with pytest.raises(Exception):
            await change_password(data, mock_request, mock_user, mock_auth_service, mock_db)

    async def test_password_change_successful(self, mocker):
        """Test successful password change."""
        mock_request = mocker.Mock(spec=Request)

        mock_user = User(
            id=1,
            email="test@example.com",
            pandas_username="testuser",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value
        )

        mock_auth_service = mocker.Mock()
        mock_auth_service.authenticate_user = mocker.AsyncMock(return_value=mock_user)

        mock_db = mocker.AsyncMock()

        mocker.patch('app.api.routes.auth.extract_client_metadata', return_value=("192.168.1.1", "TestAgent"))

        mock_audit = mocker.Mock()
        mock_audit.log_password_change = mocker.AsyncMock()
        mocker.patch('app.api.routes.auth.AuditService', return_value=mock_audit)

        # Mock password hashing
        mocker.patch('app.api.routes.public.generate_phonetic_password', return_value="phonetic")

        data = PasswordChangeRequest(
            current_password="oldpass",
            new_password="newpass123"
        )

        result = await change_password(data, mock_request, mock_user, mock_auth_service, mock_db)

        assert result.message == "Password changed successfully"
        assert mock_user.pandas_password == "newpass123"
        mock_audit.log_password_change.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
class TestPasswordResetRoutes:
    """Test password reset request and complete routes."""

    async def test_password_reset_request_user_exists(self, mocker):
        """Test password reset request for existing user."""
        mock_request = mocker.Mock(spec=Request)

        mock_user = User(
            id=1,
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value
        )

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        mocker.patch('app.api.routes.auth.extract_client_metadata', return_value=("192.168.1.1", "TestAgent"))

        mock_audit = mocker.Mock()
        mock_audit.log_password_reset_request = mocker.AsyncMock()
        mocker.patch('app.api.routes.auth.AuditService', return_value=mock_audit)

        mock_workflow = mocker.Mock()
        mock_workflow.trigger_workflow = mocker.AsyncMock()
        mocker.patch('app.services.workflow_service.WorkflowService', return_value=mock_workflow)

        mocker.patch('app.api.routes.auth.get_settings', return_value=mocker.Mock(FRONTEND_URL="http://localhost:8000"))

        data = PasswordResetRequestSchema(email="test@example.com")

        result = await request_password_reset(data, mock_request, mock_db)

        assert "If an account with that email exists" in result.message
        assert mock_user.password_reset_token is not None
        mock_audit.log_password_reset_request.assert_called_once()
        mock_workflow.trigger_workflow.assert_called_once()

    async def test_password_reset_request_user_not_exists(self, mocker):
        """Test password reset request for non-existent user (still returns success)."""
        mock_request = mocker.Mock(spec=Request)

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = None  # User not found
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        data = PasswordResetRequestSchema(email="nonexistent@example.com")

        result = await request_password_reset(data, mock_request, mock_db)

        # Should still return success to prevent email enumeration
        assert "If an account with that email exists" in result.message

    async def test_password_reset_complete_invalid_token(self, mocker):
        """Test password reset completion with invalid token."""
        mock_request = mocker.Mock(spec=Request)

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = None  # Token not found
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        data = PasswordResetCompleteSchema(
            token="invalid_token",
            new_password="newpass123"
        )

        with pytest.raises(Exception):
            await complete_password_reset(data, mock_request, mock_db)

    async def test_password_reset_complete_expired_token(self, mocker):
        """Test password reset completion with expired token."""
        mock_request = mocker.Mock(spec=Request)

        mock_user = User(
            id=1,
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            password_reset_token="valid_token",
            password_reset_expires=datetime.now(timezone.utc) - timedelta(hours=1)  # Expired
        )

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        data = PasswordResetCompleteSchema(
            token="valid_token",
            new_password="newpass123"
        )

        with pytest.raises(Exception):
            await complete_password_reset(data, mock_request, mock_db)

    async def test_password_reset_complete_successful(self, mocker):
        """Test successful password reset completion."""
        mock_request = mocker.Mock(spec=Request)

        mock_user = User(
            id=1,
            email="test@example.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.ADMIN.value,
            password_reset_token="valid_token",
            password_reset_expires=datetime.now(timezone.utc) + timedelta(hours=1)  # Not expired
        )

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        mocker.patch('app.api.routes.auth.extract_client_metadata', return_value=("192.168.1.1", "TestAgent"))

        mock_audit = mocker.Mock()
        mock_audit.log_password_reset_complete = mocker.AsyncMock()
        mocker.patch('app.api.routes.auth.AuditService', return_value=mock_audit)

        mocker.patch('app.api.routes.public.generate_phonetic_password', return_value="phonetic")

        data = PasswordResetCompleteSchema(
            token="valid_token",
            new_password="newpass123"
        )

        result = await complete_password_reset(data, mock_request, mock_db)

        assert result.message == "Password has been reset successfully"
        assert mock_user.password_reset_token is None
        assert mock_user.password_reset_expires is None
        mock_audit.log_password_reset_complete.assert_called_once()
