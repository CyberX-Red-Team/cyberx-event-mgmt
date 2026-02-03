"""
Integration tests for authentication endpoints.

Tests the /api/auth/* endpoints including login, logout, and session management.
"""

import pytest
from httpx import AsyncClient
from app.models.user import User


@pytest.mark.integration
@pytest.mark.auth
class TestAuthenticationEndpoints:
    """Test authentication API endpoints."""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, admin_user: User):
        """Test successful login."""
        response = await client.post(
            "/api/auth/login",
            json={
                "username": admin_user.email,
                "password": "admin123"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "user" in data
        assert data["user"]["email"] == admin_user.email
        assert "expires_at" in data
        assert "session_token" in response.cookies

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient, admin_user: User):
        """Test login with invalid password."""
        response = await client.post(
            "/api/auth/login",
            json={
                "username": admin_user.email,
                "password": "wrong_password"
            }
        )

        assert response.status_code == 401
        assert "session_token" not in response.cookies

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with non-existent user."""
        response = await client.post(
            "/api/auth/login",
            json={
                "username": "nonexistent@test.com",
                "password": "password123"
            }
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_endpoint_authenticated(
        self, client: AsyncClient, admin_user: User, admin_session_token: str
    ):
        """Test /me endpoint with valid session."""
        response = await client.get(
            "/api/auth/me",
            cookies={"session_token": admin_session_token}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == admin_user.email
        assert data["is_admin"] is True

    @pytest.mark.asyncio
    async def test_me_endpoint_unauthenticated(self, client: AsyncClient):
        """Test /me endpoint without authentication."""
        response = await client.get("/api/auth/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_endpoint_invalid_session(self, client: AsyncClient):
        """Test /me endpoint with invalid session token."""
        response = await client.get(
            "/api/auth/me",
            cookies={"session_token": "invalid_token"}
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_logout(
        self, client: AsyncClient, admin_user: User, admin_session_token: str
    ):
        """Test logout endpoint."""
        response = await client.post(
            "/api/auth/logout",
            cookies={"session_token": admin_session_token}
        )

        assert response.status_code == 200

        # Verify session is invalidated
        me_response = await client.get(
            "/api/auth/me",
            cookies={"session_token": admin_session_token}
        )
        assert me_response.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_without_session(self, client: AsyncClient):
        """Test logout without session token."""
        response = await client.post("/api/auth/logout")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_session_expiry(
        self, client: AsyncClient, admin_user: User
    ):
        """Test that sessions eventually expire."""
        # This test would need to manipulate time or session expiry settings
        # For now, just verify the session has an expiry time
        login_response = await client.post(
            "/api/auth/login",
            json={
                "username": admin_user.email,
                "password": "admin123"
            }
        )

        assert login_response.status_code == 200
        data = login_response.json()
        assert "expires_at" in data
        # Verify expires_at is in the future
        from datetime import datetime
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        assert expires_at > datetime.now(expires_at.tzinfo)


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.security
class TestAuthorizationRoles:
    """Test role-based authorization."""

    @pytest.mark.asyncio
    async def test_admin_access_to_admin_endpoint(
        self, client: AsyncClient, admin_session_token: str
    ):
        """Test that admin can access admin endpoints."""
        response = await client.get(
            "/api/admin/participants",
            cookies={"session_token": admin_session_token}
        )

        # Should return 200 (or 422 if query params required)
        assert response.status_code in [200, 422]

    @pytest.mark.asyncio
    async def test_sponsor_cannot_access_admin_endpoint(
        self, client: AsyncClient, sponsor_session_token: str
    ):
        """Test that sponsor cannot access admin-only endpoints."""
        response = await client.get(
            "/api/admin/participants",
            cookies={"session_token": sponsor_session_token}
        )

        # Should return 403 Forbidden
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_invitee_cannot_access_admin_endpoint(
        self, client: AsyncClient, invitee_session_token: str
    ):
        """Test that invitee cannot access admin endpoints."""
        response = await client.get(
            "/api/admin/participants",
            cookies={"session_token": invitee_session_token}
        )

        # Should return 403 Forbidden
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_sponsor_can_access_sponsor_endpoint(
        self, client: AsyncClient, sponsor_session_token: str
    ):
        """Test that sponsor can access sponsor endpoints."""
        response = await client.get(
            "/api/sponsor/invitees",
            cookies={"session_token": sponsor_session_token}
        )

        # Should return 200 (or 422 if query params required)
        assert response.status_code in [200, 422]
