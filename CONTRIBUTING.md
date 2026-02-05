# Contributing to CyberX Event Management System

Thank you for your interest in contributing to the CyberX Event Management System! This document provides guidelines and information for contributors.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing Requirements](#testing-requirements)
- [Security Considerations](#security-considerations)
- [Documentation](#documentation)

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior via GitHub issues.

## How to Contribute

We welcome contributions in the following areas:

### Bug Reports
- Use GitHub Issues to report bugs
- Include detailed steps to reproduce
- Provide environment details (OS, Python version, etc.)
- Include relevant logs or error messages

### Feature Requests
- Open a GitHub Issue with the "enhancement" label
- Clearly describe the feature and its use case
- Discuss implementation approach before starting work

### Code Contributions
- Bug fixes
- New features
- Performance improvements
- Documentation improvements
- Test coverage improvements

### Security Issues
- **Do NOT open public issues for security vulnerabilities**
- Follow the process in [SECURITY.md](SECURITY.md)
- Report via GitHub Security Advisories

## Development Setup

### Prerequisites

- Python 3.11 or higher
- PostgreSQL 13 or higher
- Git
- SendGrid account (for email testing)

### Local Setup

1. **Fork and Clone**
   ```bash
   # Fork the repository on GitHub, then:
   git clone https://github.com/YOUR_USERNAME/cyberx-event-mgmt.git
   cd cyberx-event-mgmt
   git remote add upstream https://github.com/CyberX-Red-Team/cyberx-event-mgmt.git
   ```

2. **Create a Branch**
   ```bash
   # Always branch from staging
   git checkout staging
   git pull upstream staging
   git checkout -b feature/your-feature-name
   ```

3. **Set Up Backend**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your local settings
   ```

5. **Initialize Database**
   ```bash
   alembic upgrade head
   python scripts/create_admin.py
   ```

6. **Run Development Server**
   ```bash
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

## Pull Request Process

### Before Submitting

1. **Update from upstream**
   ```bash
   git checkout staging
   git pull upstream staging
   git checkout your-branch
   git rebase staging
   ```

2. **Run tests** (when available)
   ```bash
   pytest backend/tests/
   ```

3. **Check code style**
   ```bash
   # Format with black (if configured)
   black backend/app/

   # Check with flake8 (if configured)
   flake8 backend/app/
   ```

4. **Update documentation**
   - Update relevant README sections
   - Add docstrings to new functions/classes
   - Update ADMIN_GUIDE.md if needed

### Submitting Pull Request

1. **Push to your fork**
   ```bash
   git push origin your-branch
   ```

2. **Create Pull Request**
   - Target the `staging` branch (not `main`)
   - Use a clear, descriptive title
   - Reference related issues (e.g., "Fixes #123")
   - Provide detailed description of changes
   - Include screenshots for UI changes
   - List any breaking changes

3. **PR Template**
   ```markdown
   ## Description
   Brief description of changes

   ## Motivation and Context
   Why is this change needed? What problem does it solve?

   ## Type of Change
   - [ ] Bug fix (non-breaking change)
   - [ ] New feature (non-breaking change)
   - [ ] Breaking change (fix or feature that would cause existing functionality to change)
   - [ ] Documentation update

   ## How Has This Been Tested?
   Describe the tests you ran

   ## Checklist
   - [ ] Code follows project style guidelines
   - [ ] Self-review completed
   - [ ] Comments added for complex logic
   - [ ] Documentation updated
   - [ ] No new warnings generated
   - [ ] Tests added/updated (if applicable)
   - [ ] All tests passing
   ```

### Review Process

1. Maintainers will review your PR
2. Address any requested changes
3. Once approved, a maintainer will merge your PR
4. Your contribution will be included in the next release

## Coding Standards

### Python Style

- Follow [PEP 8](https://pep8.org/)
- Use type hints for function signatures
- Maximum line length: 120 characters
- Use descriptive variable names

### Code Organization

```python
# Good: Clear, typed function with docstring
async def get_participant_by_email(
    db: AsyncSession,
    email: str
) -> Optional[User]:
    """
    Retrieve a participant by email address.

    Args:
        db: Database session
        email: Email address to search for

    Returns:
        User object if found, None otherwise
    """
    result = await db.execute(
        select(User).where(User.email == email)
    )
    return result.scalar_one_or_none()
```

### Architecture Patterns

- **Controllers**: Keep route handlers thin, delegate to services
- **Services**: Business logic layer, orchestrate operations
- **Models**: SQLAlchemy models, database schema
- **Schemas**: Pydantic models for validation
- **Utils**: Shared utility functions

### Database

- Use Alembic migrations for schema changes
- Never commit raw SQL without parameterization
- Use SQLAlchemy ORM for queries
- Add appropriate indexes for query performance

### Security Best Practices

- Never log sensitive data (passwords, tokens, keys)
- Use parameterized queries (SQLAlchemy handles this)
- Validate all user input with Pydantic schemas
- Use appropriate HTTP status codes
- Add audit logging for security-relevant actions

## Testing Requirements

### Test Coverage Goals

- **New Features**: Minimum 70% coverage
- **Bug Fixes**: Add test that reproduces the bug
- **Critical Paths**: Authentication, authorization, data validation

### Test Structure

```python
# backend/tests/test_feature.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_participant(client: AsyncClient, auth_headers):
    """Test creating a new participant."""
    response = await client.post(
        "/api/admin/participants",
        json={
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
            "country": "USA"
        },
        headers=auth_headers
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
```

### Running Tests

```bash
# Run all tests
pytest backend/tests/

# Run specific test file
pytest backend/tests/test_participants.py

# Run with coverage
pytest --cov=backend/app backend/tests/

# Run with verbose output
pytest -v backend/tests/
```

## Security Considerations

### Sensitive Data

- Never commit `.env` files
- Never commit API keys or credentials
- Use environment variables for secrets
- Encrypt sensitive fields in database

### Security Features to Maintain

- CSRF protection on state-changing endpoints
- Session-based authentication with secure cookies
- bcrypt password hashing (cost factor 12+)
- Role-based access control (RBAC)
- Input validation with Pydantic
- SQL injection prevention via ORM
- SendGrid webhook signature verification

### Security Review Checklist

When contributing security-related code:
- [ ] Input validation implemented
- [ ] Authentication/authorization checked
- [ ] Sensitive data encrypted or excluded from logs
- [ ] Rate limiting considered (if applicable)
- [ ] SQL injection prevention verified
- [ ] XSS prevention verified
- [ ] CSRF protection verified

## Documentation

### Code Documentation

- Add docstrings to all public functions/classes
- Use Google-style docstrings
- Document parameters, return values, and exceptions
- Include usage examples for complex functions

### User Documentation

- Update README.md for user-facing changes
- Update ADMIN_GUIDE.md for administrative features
- Add inline comments for complex logic
- Create issue templates for common scenarios

### API Documentation

- FastAPI auto-generates OpenAPI docs
- Add detailed descriptions to route handlers
- Document request/response schemas
- Include example payloads

## Commit Messages

Use clear, descriptive commit messages:

```
Add feature: brief description

- Detailed change 1
- Detailed change 2
- Related documentation updates

Fixes #123

Co-Authored-By: Name <email>
```

### Commit Message Guidelines

- Use present tense ("Add feature" not "Added feature")
- Use imperative mood ("Move cursor to..." not "Moves cursor to...")
- Reference issues and pull requests
- Keep first line under 72 characters
- Add detailed description after blank line

## Questions?

- Open a GitHub Discussion for questions
- Join our community channels (if available)
- Check existing issues and documentation
- Ask maintainers for clarification

## License

By contributing to this project, you agree that your contributions will be licensed under the Apache License 2.0.

Thank you for contributing to CyberX Event Management System! 🎯
