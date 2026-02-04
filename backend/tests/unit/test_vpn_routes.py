"""Unit tests for VPN routes - focused on coverage."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from app.models.user import User, UserRole
from app.api.routes.vpn import (
    list_vpn_credentials,
    get_vpn_stats,
    get_vpn_credential,
    get_my_vpn_credentials,
    get_my_vpn_config,
    get_available_vpn_count,
)


@pytest.fixture
def mock_admin_user():
    """Create a mock admin user."""
    return User(
        id=1,
        email="admin@test.com",
        first_name="Admin",
        last_name="User",
        country="USA",
        role=UserRole.ADMIN.value,
        is_admin=True
    )


@pytest.fixture
def mock_regular_user():
    """Create a mock regular user."""
    return User(
        id=2,
        email="user@test.com",
        first_name="Regular",
        last_name="User",
        country="USA",
        role=UserRole.INVITEE.value,
        is_admin=False
    )


class TestListVPNCredentials:
    """Test GET /api/vpn/credentials endpoint."""

    async def test_list_vpn_credentials_empty(self, mock_admin_user, mocker):
        """Test listing VPN credentials with no results."""
        mock_vpn_service = mocker.Mock()
        mock_vpn_service.list_credentials = AsyncMock(return_value=([], 0))
        mock_db = mocker.Mock()
        mocker.patch('app.api.routes.vpn.build_vpn_response', AsyncMock(return_value=Mock()))

        result = await list_vpn_credentials(
            page=1,
            page_size=50,
            is_available=None,
            search=None,
            current_user=mock_admin_user,
            service=mock_vpn_service,
            db=mock_db
        )

        assert result.total == 0
        assert len(result.items) == 0

    async def test_list_vpn_credentials_with_filters(self, mock_admin_user, mocker):
        """Test listing VPN credentials with filters."""
        mock_vpn_service = mocker.Mock()
        mock_vpn_service.list_credentials = AsyncMock(return_value=([], 0))
        mock_db = mocker.Mock()

        result = await list_vpn_credentials(
            page=1,
            page_size=10,
            is_available=True,
            search="10.0",
            current_user=mock_admin_user,
            service=mock_vpn_service,
            db=mock_db
        )

        mock_vpn_service.list_credentials.assert_called_once_with(
            page=1,
            page_size=10,
            is_available=True,
            search="10.0"
        )


class TestGetVPNStats:
    """Test GET /api/vpn/stats endpoint."""

    async def test_get_vpn_stats(self, mock_admin_user, mocker):
        """Test getting VPN statistics."""
        mock_stats = {
            "total_credentials": 100,
            "assigned_count": 25,
            "available_count": 75,
            "assignment_rate": 0.25
        }
        mock_vpn_service = mocker.Mock()
        mock_vpn_service.get_statistics = AsyncMock(return_value=mock_stats)

        result = await get_vpn_stats(
            current_user=mock_admin_user,
            service=mock_vpn_service
        )

        assert result.total_credentials == 100
        assert result.assigned_count == 25
        assert result.available_count == 75


class TestGetVPNCredential:
    """Test GET /api/vpn/credentials/{vpn_id} endpoint."""

    async def test_get_vpn_credential_not_found(self, mock_admin_user, mocker):
        """Test getting non-existent VPN credential."""
        mock_db = mocker.Mock()
        mock_vpn_service = mocker.Mock()
        mock_vpn_service.get_credential_by_id = AsyncMock(return_value=None)

        with pytest.raises(Exception):
            await get_vpn_credential(
                vpn_id=999,
                current_user=mock_admin_user,
                service=mock_vpn_service,
                db=mock_db
            )


class TestGetMyVPNCredentials:
    """Test GET /api/vpn/my-credentials endpoint."""

    async def test_get_my_vpn_credentials_none(self, mock_regular_user, mocker):
        """Test getting user's VPN credentials when none exist."""
        mock_db = mocker.Mock()
        mock_vpn_service = mocker.Mock()
        mock_vpn_service.get_user_credentials = AsyncMock(return_value=[])

        mocker.patch('app.api.routes.vpn.build_vpn_response', AsyncMock(return_value=Mock()))

        result = await get_my_vpn_credentials(
            current_user=mock_regular_user,
            service=mock_vpn_service,
            db=mock_db
        )

        assert result.total == 0
        assert len(result.credentials) == 0


class TestGetMyVPNConfig:
    """Test GET /api/vpn/my-config endpoint."""

    async def test_get_my_vpn_config_not_found(self, mock_regular_user, mocker):
        """Test getting VPN config when none assigned."""
        mock_vpn_service = mocker.Mock()
        mock_vpn_service.get_user_credentials = AsyncMock(return_value=[])

        with pytest.raises(Exception):
            await get_my_vpn_config(
                current_user=mock_regular_user,
                service=mock_vpn_service
            )


class TestGetAvailableVPNCount:
    """Test GET /api/vpn/available-count endpoint."""

    async def test_get_available_vpn_count(self, mock_regular_user, mocker):
        """Test getting available VPN count."""
        mock_vpn_service = mocker.Mock()
        mock_vpn_service.get_available_count = AsyncMock(return_value=50)

        result = await get_available_vpn_count(
            current_user=mock_regular_user,
            service=mock_vpn_service
        )

        assert result["available_count"] == 50
