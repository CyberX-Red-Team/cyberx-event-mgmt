"""
Pytest configuration and fixtures for CyberX Event Management System tests.

This module provides shared fixtures for database, authentication, test client,
and common test data.
"""

import asyncio
import os
import sys
from typing import AsyncGenerator, Generator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from app.database import Base, get_db
from app.models.user import User, UserRole
from app.models.event import Event
from app.config import Settings, get_settings
from app.utils.security import hash_password
from app.utils.encryption import init_encryptor, generate_encryption_key


# ============================================================================
# Test Configuration
# ============================================================================

@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """
    Provide test-specific settings.

    Uses in-memory SQLite database for tests.
    """
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        SECRET_KEY="test-secret-key-for-testing-only",
        CSRF_SECRET_KEY="test-csrf-key-for-testing-only",
        ENCRYPTION_KEY=generate_encryption_key(),
        DEBUG=True,
        ALLOWED_HOSTS="localhost,127.0.0.1",
        SENDGRID_API_KEY="SG.test-key",
        SENDGRID_FROM_EMAIL="test@example.com",
        SENDGRID_FROM_NAME="Test",
        SENDGRID_SANDBOX_MODE=True,
        POWERDNS_API_URL="http://test-dns.local",
        POWERDNS_USERNAME="test",
        POWERDNS_PASSWORD="test",
        VPN_SERVER_PUBLIC_KEY="test-key",
        VPN_SERVER_ENDPOINT="test.vpn.local:51820",
        FRONTEND_URL="http://localhost:8000",
    )


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """
    Create event loop for async tests.

    Required for pytest-asyncio to work properly.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest_asyncio.fixture(scope="function")
async def async_engine(test_settings: Settings):
    """
    Create async database engine for tests.

    Uses in-memory SQLite with StaticPool to ensure all connections
    share the same in-memory database.
    """
    engine = create_async_engine(
        test_settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide database session for tests.

    Creates a new session for each test and rolls back after the test.
    """
    async_session = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(async_engine, db_session: AsyncSession, test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    """
    Provide HTTP test client.

    Overrides the database session dependency to use the test database.

    IMPORTANT: Uses a shared session approach to avoid session isolation issues.
    The same db_session instance is reused across all dependency injections.
    """
    # Initialize encryption
    init_encryptor(test_settings.ENCRYPTION_KEY)

    # Clear rate limit cache for tests
    from app.api.routes import auth
    auth._login_rate_limit_cache.clear()

    # Override database session dependency to return THE SAME session
    # This is critical - we can't create new sessions or the data won't be visible
    async def override_get_db():
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

    # Override settings dependency
    def override_get_settings():
        return test_settings

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    # Disable CSRF middleware for integration tests by making _is_exempt always return True
    # CSRF middleware should be tested separately with dedicated CSRF tests
    from app.middleware.csrf import CSRFMiddleware

    # Monkey-patch the _is_exempt method to always return True
    # Store original for cleanup
    original_is_exempt = CSRFMiddleware._is_exempt
    CSRFMiddleware._is_exempt = lambda self, path: True

    # Create client
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client

    # Restore original _is_exempt method
    CSRFMiddleware._is_exempt = original_is_exempt

    # Clear overrides
    app.dependency_overrides.clear()

    # Clear rate limit cache after test
    auth._login_rate_limit_cache.clear()


# ============================================================================
# User Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """
    Create and return an admin user for testing.
    """
    user = User(
        email="admin@test.com",
        first_name="Admin",
        last_name="User",
        country="USA",
        role=UserRole.ADMIN.value,
        is_admin=True,
        is_active=True,
        confirmed="YES",
        password_hash=hash_password("admin123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def sponsor_user(db_session: AsyncSession) -> User:
    """
    Create and return a sponsor user for testing.
    """
    user = User(
        email="sponsor@test.com",
        first_name="Sponsor",
        last_name="User",
        country="USA",
        role=UserRole.SPONSOR.value,
        is_active=True,
        confirmed="YES",
        password_hash=hash_password("sponsor123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def invitee_user(db_session: AsyncSession, sponsor_user: User) -> User:
    """
    Create and return an invitee user for testing.
    """
    user = User(
        email="invitee@test.com",
        first_name="Invitee",
        last_name="User",
        country="USA",
        role=UserRole.INVITEE.value,
        sponsor_id=sponsor_user.id,
        is_active=True,
        confirmed="UNKNOWN",
        password_hash=hash_password("invitee123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ============================================================================
# Authentication Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def admin_session_token(client: AsyncClient, admin_user: User) -> str:
    """
    Authenticate as admin and return session token.
    """
    response = await client.post(
        "/api/auth/login",
        json={"username": admin_user.email, "password": "admin123"}
    )
    assert response.status_code == 200
    return response.cookies.get("session_token")


@pytest_asyncio.fixture
async def sponsor_session_token(client: AsyncClient, sponsor_user: User) -> str:
    """
    Authenticate as sponsor and return session token.
    """
    response = await client.post(
        "/api/auth/login",
        json={"username": sponsor_user.email, "password": "sponsor123"}
    )
    assert response.status_code == 200
    return response.cookies.get("session_token")


@pytest_asyncio.fixture
async def invitee_session_token(client: AsyncClient, invitee_user: User) -> str:
    """
    Authenticate as invitee and return session token.
    """
    response = await client.post(
        "/api/auth/login",
        json={"username": invitee_user.email, "password": "invitee123"}
    )
    assert response.status_code == 200
    return response.cookies.get("session_token")


@pytest_asyncio.fixture
async def authenticated_admin_client(client: AsyncClient, admin_session_token: str) -> AsyncClient:
    """
    Provide client authenticated as admin.
    """
    client.cookies.set("session_token", admin_session_token)
    return client


# ============================================================================
# Event Fixtures
# ============================================================================

@pytest_asyncio.fixture
async def active_event(db_session: AsyncSession) -> Event:
    """
    Create and return an active event for testing.
    """
    from datetime import datetime, timezone, timedelta

    event = Event(
        name="Test CyberX 2026",
        year=2026,
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
        end_date=datetime.now(timezone.utc) + timedelta(days=37),
        registration_open=True,
        is_active=True,
        test_mode=False,
        terms_version="1.0",
        max_participants=100,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    return event


# ============================================================================
# Helper Functions
# ============================================================================

@pytest.fixture
def sample_participant_data() -> dict:
    """
    Provide sample participant data for creating users.
    """
    return {
        "email": "newuser@test.com",
        "first_name": "New",
        "last_name": "User",
        "country": "USA",
    }


# ============================================================================
# Markers
# ============================================================================

def pytest_configure(config):
    """
    Configure pytest markers.
    """
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "e2e: mark test as an end-to-end test"
    )
