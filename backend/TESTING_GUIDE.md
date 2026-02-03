# Testing Guide

## Overview

This guide covers the automated testing framework for the CyberX Event Management System. We use **pytest** with async support for comprehensive test coverage.

**Current Status**: Testing framework implemented
**Coverage Target**: 70% code coverage
**Test Types**: Unit, Integration, End-to-End

---

## Quick Start

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov

# Run specific test file
pytest tests/unit/test_encryption.py

# Run tests matching a pattern
pytest -k "auth"

# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run with verbose output
pytest -v

# Run with extra test summary
pytest -ra
```

### Installation

```bash
# Install test dependencies
pip install -r requirements.txt

# Verify pytest is installed
pytest --version
```

---

## Test Structure

```
backend/
├── tests/
│   ├── conftest.py          # Shared fixtures and configuration
│   ├── unit/                # Unit tests (fast, isolated)
│   │   ├── test_encryption.py
│   │   ├── test_security.py
│   │   └── ...
│   ├── integration/         # Integration tests (API endpoints)
│   │   ├── test_auth.py
│   │   ├── test_participants.py
│   │   └── ...
│   └── e2e/                 # End-to-end tests (complete workflows)
│       └── ...
└── pytest.ini               # Pytest configuration
```

---

## Test Categories

### Unit Tests (`@pytest.mark.unit`)

**Characteristics**:
- Fast (< 0.1s each)
- No external dependencies
- Test single functions/classes in isolation
- Mock external dependencies

**Example**:
```python
import pytest
from app.utils.security import hash_password, verify_password

@pytest.mark.unit
def test_password_hashing():
    password = "test123"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
```

### Integration Tests (`@pytest.mark.integration`)

**Characteristics**:
- Test multiple components together
- Use test database (in-memory SQLite)
- Test API endpoints
- May be slower (< 1s each)

**Example**:
```python
import pytest
from httpx import AsyncClient

@pytest.mark.integration
@pytest.mark.asyncio
async def test_login(client: AsyncClient, admin_user):
    response = await client.post(
        "/api/auth/login",
        json={"username": admin_user.email, "password": "admin123"}
    )
    assert response.status_code == 200
```

### End-to-End Tests (`@pytest.mark.e2e`)

**Characteristics**:
- Test complete user workflows
- May require running server
- Slowest tests (several seconds)
- Test critical paths

---

## Available Fixtures

Fixtures are defined in `tests/conftest.py` and available to all tests.

### Database Fixtures

```python
async def test_with_database(db_session: AsyncSession):
    """Use database session."""
    user = User(email="test@example.com", ...)
    db_session.add(user)
    await db_session.commit()
```

### Client Fixtures

```python
async def test_api_endpoint(client: AsyncClient):
    """Use HTTP test client."""
    response = await client.get("/api/some-endpoint")
    assert response.status_code == 200
```

### User Fixtures

```python
async def test_with_admin(admin_user: User):
    """Admin user already created in database."""
    assert admin_user.is_admin is True

async def test_with_sponsor(sponsor_user: User):
    """Sponsor user already created."""
    assert sponsor_user.role == UserRole.SPONSOR.value

async def test_with_invitee(invitee_user: User):
    """Invitee user already created."""
    assert invitee_user.role == UserRole.INVITEE.value
```

### Authentication Fixtures

```python
async def test_authenticated_request(
    client: AsyncClient,
    admin_session_token: str
):
    """Make authenticated API request."""
    response = await client.get(
        "/api/admin/participants",
        cookies={"session_token": admin_session_token}
    )
```

### Event Fixtures

```python
async def test_with_event(active_event: Event):
    """Active event already created."""
    assert active_event.is_active is True
```

---

## Writing Tests

### Test Naming

- Test files: `test_*.py`
- Test functions: `test_*`
- Test classes: `Test*`

```python
# Good
def test_user_creation():
    ...

class TestAuthentication:
    def test_login_success(self):
        ...
```

### Async Tests

Use `@pytest.mark.asyncio` for async tests:

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

### Test Markers

Mark tests for selective running:

```python
@pytest.mark.unit  # Unit test
@pytest.mark.integration  # Integration test
@pytest.mark.slow  # Slow test
@pytest.mark.security  # Security test
@pytest.mark.auth  # Authentication test

@pytest.mark.skip(reason="Not implemented yet")
@pytest.mark.skipif(condition, reason="Conditional skip")
```

### Assertions

Use clear, descriptive assertions:

```python
# Good
assert user.email == "test@example.com"
assert response.status_code == 200
assert len(users) == 3

# Use pytest helpers
assert "error" in response.json()
assert user.is_active is True

# Multiple assertions
assert response.status_code == 200
data = response.json()
assert "user" in data
assert data["user"]["email"] == "test@example.com"
```

### Testing Exceptions

```python
import pytest
from app.api.exceptions import NotFoundException

def test_exception_raised():
    with pytest.raises(NotFoundException):
        service.get_nonexistent_user(999)

def test_exception_message():
    with pytest.raises(ValueError, match="Invalid email"):
        validate_email("not-an-email")
```

---

## Best Practices

### 1. Test Independence

Each test should be independent and not rely on other tests:

```python
# Good - each test creates its own data
async def test_user_creation(db_session):
    user = User(email="test@example.com")
    db_session.add(user)
    await db_session.commit()

async def test_user_deletion(db_session):
    user = User(email="test2@example.com")
    db_session.add(user)
    await db_session.commit()
    # ... test deletion
```

### 2. Use Fixtures for Setup

Don't repeat setup code - use fixtures:

```python
# Good
@pytest.fixture
async def user_with_vpn(db_session):
    user = User(...)
    vpn = VPNCredential(...)
    db_session.add(user)
    db_session.add(vpn)
    await db_session.commit()
    return user

async def test_vpn_assignment(user_with_vpn):
    assert user_with_vpn.vpn is not None
```

### 3. Test One Thing

Each test should focus on one behavior:

```python
# Good - separate tests
async def test_login_success(client, admin_user):
    response = await client.post("/api/auth/login", ...)
    assert response.status_code == 200

async def test_login_invalid_credentials(client, admin_user):
    response = await client.post("/api/auth/login", ...)
    assert response.status_code == 401

# Not as good - multiple behaviors in one test
async def test_login(client, admin_user):
    # Test success
    response1 = await client.post(...)
    assert response1.status_code == 200
    # Test failure
    response2 = await client.post(...)
    assert response2.status_code == 401
```

### 4. Descriptive Test Names

Use clear, descriptive names:

```python
# Good
def test_user_creation_with_valid_email():
    ...

def test_user_creation_fails_with_duplicate_email():
    ...

# Not as good
def test_user():
    ...

def test_user2():
    ...
```

### 5. Arrange-Act-Assert Pattern

Structure tests clearly:

```python
async def test_participant_creation(db_session):
    # Arrange
    email = "newuser@test.com"
    service = ParticipantService(db_session)

    # Act
    user = await service.create_participant(
        email=email,
        first_name="Test",
        last_name="User",
        country="USA"
    )

    # Assert
    assert user.email == email
    assert user.is_active is True
```

---

## Coverage Reports

### Generating Coverage

```bash
# Run tests with coverage
pytest --cov

# Generate HTML report
pytest --cov --cov-report=html

# View HTML report
open htmlcov/index.html
```

### Coverage Thresholds

The pytest configuration enforces minimum coverage:

```ini
[pytest]
addopts = --cov-fail-under=0  # Currently 0%, increase as coverage improves
```

### Checking Coverage

```bash
# Check coverage for specific module
pytest --cov=app.services.participant_service

# Show missing lines
pytest --cov --cov-report=term-missing
```

---

## Continuous Integration

### GitHub Actions

Create `.github/workflows/test.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt

      - name: Run tests
        run: |
          cd backend
          pytest --cov --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./backend/coverage.xml
```

---

## Debugging Tests

### Running Single Test

```bash
# Run specific test
pytest tests/unit/test_encryption.py::TestFieldEncryptor::test_encrypt_decrypt_simple

# With verbose output
pytest -v tests/unit/test_encryption.py::test_key_generation
```

### Using Debugger

```python
import pytest

def test_with_breakpoint():
    user = create_user()
    breakpoint()  # Debugger stops here
    assert user.email == "test@example.com"
```

### Print Debugging

```bash
# Show print statements
pytest -s

# Show local variables on failure
pytest --showlocals
```

### Verbose Mode

```bash
# Show test names as they run
pytest -v

# Show extra test summary
pytest -ra
```

---

## Common Testing Patterns

### Testing Async Functions

```python
@pytest.mark.asyncio
async def test_async_service(db_session):
    service = SomeService(db_session)
    result = await service.async_method()
    assert result is not None
```

### Testing API Endpoints

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_participant(client, admin_session_token):
    response = await client.post(
        "/api/admin/participants",
        json={
            "email": "new@test.com",
            "first_name": "New",
            "last_name": "User",
            "country": "USA"
        },
        cookies={"session_token": admin_session_token}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "new@test.com"
```

### Testing Error Handling

```python
@pytest.mark.asyncio
async def test_duplicate_email_error(db_session):
    service = ParticipantService(db_session)

    # Create first user
    await service.create_participant(
        email="test@test.com",
        first_name="Test",
        last_name="User",
        country="USA"
    )

    # Attempt to create duplicate should raise error
    with pytest.raises(IntegrityError):
        await service.create_participant(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA"
        )
```

---

## Roadmap

### Current Status ✅
- [x] pytest framework configured
- [x] Fixtures for database, client, users
- [x] Sample unit tests (encryption, security)
- [x] Sample integration tests (auth endpoints)
- [x] Coverage reporting setup

### Phase 2 (Next 2 weeks)
- [ ] Unit tests for all services (target: 50+ tests)
- [ ] Integration tests for all API endpoints (target: 100+ tests)
- [ ] Increase coverage to 40-50%
- [ ] CI/CD pipeline setup

### Phase 3 (Following 2 weeks)
- [ ] E2E tests for critical workflows
- [ ] Performance tests
- [ ] Increase coverage to 70%
- [ ] Load testing integration

---

**Last Updated**: 2026-02-03
**Framework**: pytest + pytest-asyncio + pytest-cov
**Coverage Goal**: 70%
**Status**: ✅ Framework ready for development
