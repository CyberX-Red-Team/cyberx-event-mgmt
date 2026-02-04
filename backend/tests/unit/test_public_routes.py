"""Unit tests for public registration API routes.

Tests route-level logic, validation, error handling, and response formatting.
All service dependencies are mocked to isolate route behavior.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock

from app.api.routes.public import (
    generate_username,
    generate_password,
    generate_phonetic_password,
    get_confirmation_terms,
    confirm_participation,
    decline_participation,
    get_countries
)
from app.models.user import User, UserRole
from app.models.event import Event


@pytest.mark.unit
class TestPasswordGeneration:
    """Test password generation utilities."""

    def test_generate_password_length(self):
        """Test password generation with correct length."""
        password = generate_password(12)
        assert len(password) == 12

    def test_generate_password_custom_length(self):
        """Test password generation with custom length."""
        password = generate_password(16)
        assert len(password) == 16

    def test_generate_password_has_required_characters(self):
        """Test that generated password contains required character types."""
        password = generate_password(12)

        has_uppercase = any(c.isupper() for c in password)
        has_lowercase = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in "!@#$%^&*" for c in password)

        assert has_uppercase
        assert has_lowercase
        assert has_digit
        assert has_special

    def test_generate_phonetic_password_uppercase(self):
        """Test phonetic password generation for uppercase letters."""
        result = generate_phonetic_password("A")
        assert result == "ALPHA"

    def test_generate_phonetic_password_lowercase(self):
        """Test phonetic password generation for lowercase letters."""
        result = generate_phonetic_password("a")
        assert result == "alpha"

    def test_generate_phonetic_password_digits(self):
        """Test phonetic password generation for digits."""
        result = generate_phonetic_password("123")
        assert result == "One-Two-Three"

    def test_generate_phonetic_password_symbols(self):
        """Test phonetic password generation for symbols."""
        result = generate_phonetic_password("!@")
        assert result == "Exclamation-At"

    def test_generate_phonetic_password_mixed(self):
        """Test phonetic password generation for mixed characters."""
        result = generate_phonetic_password("Aa1!")
        assert result == "ALPHA-alpha-One-Exclamation"


@pytest.mark.unit
@pytest.mark.asyncio
class TestUsernameGeneration:
    """Test username generation utility."""

    async def test_generate_username_simple(self, mocker):
        """Test generating username when no conflict."""
        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        username = await generate_username("John", "Smith", mock_db)

        assert username == "jsmith"

    async def test_generate_username_with_conflict(self, mocker):
        """Test generating username when base name is taken."""
        mock_db = mocker.AsyncMock()

        # First call returns existing user (conflict), second call returns None (available)
        mock_result1 = mocker.Mock()
        mock_result1.scalar_one_or_none.return_value = Mock(id=1)  # Exists

        mock_result2 = mocker.Mock()
        mock_result2.scalar_one_or_none.return_value = None  # Available

        mock_db.execute = mocker.AsyncMock(side_effect=[mock_result1, mock_result2])

        username = await generate_username("John", "Smith", mock_db)

        assert username == "jsmith2"

    async def test_generate_username_multiple_conflicts(self, mocker):
        """Test generating username with multiple conflicts."""
        mock_db = mocker.AsyncMock()

        # First 3 calls return conflicts, 4th is available
        mock_results = [
            mocker.Mock(scalar_one_or_none=lambda: Mock(id=1)),  # jsmith taken
            mocker.Mock(scalar_one_or_none=lambda: Mock(id=2)),  # jsmith2 taken
            mocker.Mock(scalar_one_or_none=lambda: Mock(id=3)),  # jsmith3 taken
            mocker.Mock(scalar_one_or_none=lambda: None),        # jsmith4 available
        ]

        mock_db.execute = mocker.AsyncMock(side_effect=mock_results)

        username = await generate_username("John", "Smith", mock_db)

        assert username == "jsmith4"


@pytest.mark.unit
@pytest.mark.asyncio
class TestConfirmationTermsRoute:
    """Test GET /api/public/confirm/terms endpoint."""

    async def test_get_confirmation_terms_invalid_code(self, mocker):
        """Test getting terms with invalid confirmation code."""
        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        with pytest.raises(Exception):
            await get_confirmation_terms(code="invalid_code", db=mock_db)

    async def test_get_confirmation_terms_already_confirmed(self, mocker):
        """Test getting terms for already confirmed user."""
        mock_user = Mock()
        mock_user.confirmed = "YES"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        result = await get_confirmation_terms(code="valid_code", db=mock_db)

        assert result["already_confirmed"] is True

    async def test_get_confirmation_terms_already_declined(self, mocker):
        """Test getting terms for user who already declined."""
        mock_user = Mock()
        mock_user.confirmed = "NO"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        result = await get_confirmation_terms(code="valid_code", db=mock_db)

        assert result["already_declined"] is True

    async def test_get_confirmation_terms_no_active_event(self, mocker):
        """Test getting terms when no active event exists."""
        mock_user = Mock()
        mock_user.confirmed = "UNKNOWN"
        mock_user.first_name = "Test"
        mock_user.last_name = "User"
        mock_user.email = "test@test.com"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        # Mock EventService
        mock_event_service = mocker.Mock()
        mock_event_service.get_current_event = mocker.AsyncMock(return_value=None)
        mocker.patch('app.api.routes.public.EventService', return_value=mock_event_service)

        result = await get_confirmation_terms(code="valid_code", db=mock_db)

        assert result["no_active_event"] is True
        assert result["user"]["first_name"] == "Test"

    async def test_get_confirmation_terms_success(self, mocker):
        """Test successfully getting confirmation terms."""
        mock_user = Mock()
        mock_user.confirmed = "UNKNOWN"
        mock_user.first_name = "Test"
        mock_user.last_name = "User"
        mock_user.email = "test@test.com"

        mock_event = Mock()
        mock_event.name = "CyberX 2026"
        mock_event.year = 2026
        mock_event.terms_content = "Terms and conditions..."
        mock_event.terms_version = "1.0"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        # Mock EventService
        mock_event_service = mocker.Mock()
        mock_event_service.get_current_event = mocker.AsyncMock(return_value=mock_event)
        mocker.patch('app.api.routes.public.EventService', return_value=mock_event_service)

        result = await get_confirmation_terms(code="valid_code", db=mock_db)

        assert "user" in result
        assert result["user"]["first_name"] == "Test"
        assert "terms" in result
        assert result["terms"]["version"] == "1.0"
        assert "event" in result
        assert result["event"]["year"] == 2026


@pytest.mark.unit
@pytest.mark.asyncio
class TestConfirmParticipationRoute:
    """Test POST /api/public/confirm/accept endpoint."""

    async def test_confirm_participation_missing_code(self, mocker):
        """Test confirming without confirmation code."""
        mock_request = mocker.Mock()
        mock_db = mocker.AsyncMock()
        data = {"terms_accepted": True}

        with pytest.raises(Exception):
            await confirm_participation(request=mock_request, data=data, db=mock_db)

    async def test_confirm_participation_missing_terms_accepted(self, mocker):
        """Test confirming without accepting terms."""
        mock_request = mocker.Mock()
        mock_db = mocker.AsyncMock()
        data = {"confirmation_code": "code123"}

        with pytest.raises(Exception):
            await confirm_participation(request=mock_request, data=data, db=mock_db)

    async def test_confirm_participation_invalid_code(self, mocker):
        """Test confirming with invalid code."""
        mock_request = mocker.Mock()
        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        data = {"confirmation_code": "invalid", "terms_accepted": True}

        with pytest.raises(Exception):
            await confirm_participation(request=mock_request, data=data, db=mock_db)

    async def test_confirm_participation_already_confirmed(self, mocker):
        """Test confirming when already confirmed."""
        mock_request = mocker.Mock()

        mock_user = Mock()
        mock_user.confirmed = "YES"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        data = {"confirmation_code": "code123", "terms_accepted": True, "terms_version": "1.0"}

        with pytest.raises(Exception):
            await confirm_participation(request=mock_request, data=data, db=mock_db)

    async def test_confirm_participation_success_invitee(self, mocker):
        """Test successful confirmation for invitee (generates new password)."""
        mock_request = mocker.Mock()
        mock_request.client = mocker.Mock(host="192.168.1.1")
        mock_request.headers = {"user-agent": "TestBrowser"}

        mock_user = Mock()
        mock_user.id = 1
        mock_user.confirmed = "UNKNOWN"
        mock_user.first_name = "Test"
        mock_user.last_name = "User"
        mock_user.email = "test@test.com"
        mock_user.role = "invitee"
        mock_user.pandas_username = None
        mock_user.pandas_password = None

        mock_event = Mock()
        mock_event.id = 1
        mock_event.name = "CyberX 2026"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)
        mock_db.commit = mocker.AsyncMock()
        mock_db.refresh = mocker.AsyncMock()

        # Mock services
        mock_audit = mocker.Mock()
        mock_audit.log_terms_acceptance = mocker.AsyncMock()
        mocker.patch('app.api.routes.public.AuditService', return_value=mock_audit)

        mock_event_service = mocker.Mock()
        mock_event_service.get_current_event = mocker.AsyncMock(return_value=mock_event)
        mocker.patch('app.api.routes.public.EventService', return_value=mock_event_service)

        mock_workflow = mocker.Mock()
        mock_workflow.trigger_workflow = mocker.AsyncMock()
        mocker.patch('app.api.routes.public.WorkflowService', return_value=mock_workflow)

        # Mock username generation
        mocker.patch('app.api.routes.public.generate_username', return_value="tuser")

        data = {
            "confirmation_code": "code123",
            "terms_accepted": True,
            "terms_version": "1.0"
        }

        result = await confirm_participation(request=mock_request, data=data, db=mock_db)

        assert result["success"] is True
        assert "confirmed" in result["message"].lower()
        assert mock_user.confirmed == "YES"
        assert mock_user.pandas_username == "tuser"
        assert mock_user.pandas_password is not None  # Password was generated

    async def test_confirm_participation_success_sponsor_keeps_password(self, mocker):
        """Test successful confirmation for sponsor (keeps existing password)."""
        mock_request = mocker.Mock()
        mock_request.client = mocker.Mock(host="192.168.1.1")
        mock_request.headers = {"user-agent": "TestBrowser"}

        mock_user = Mock()
        mock_user.id = 1
        mock_user.confirmed = "UNKNOWN"
        mock_user.first_name = "Test"
        mock_user.last_name = "Sponsor"
        mock_user.email = "sponsor@test.com"
        mock_user.role = "sponsor"
        mock_user.pandas_username = "tsponsor"
        mock_user.pandas_password = "existing_password"

        mock_event = Mock()
        mock_event.id = 1
        mock_event.name = "CyberX 2026"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)
        mock_db.commit = mocker.AsyncMock()
        mock_db.refresh = mocker.AsyncMock()

        # Mock services
        mock_audit = mocker.Mock()
        mock_audit.log_terms_acceptance = mocker.AsyncMock()
        mocker.patch('app.api.routes.public.AuditService', return_value=mock_audit)

        mock_event_service = mocker.Mock()
        mock_event_service.get_current_event = mocker.AsyncMock(return_value=mock_event)
        mocker.patch('app.api.routes.public.EventService', return_value=mock_event_service)

        mock_workflow = mocker.Mock()
        mock_workflow.trigger_workflow = mocker.AsyncMock()
        mocker.patch('app.api.routes.public.WorkflowService', return_value=mock_workflow)

        data = {
            "confirmation_code": "code123",
            "terms_accepted": True,
            "terms_version": "1.0"
        }

        result = await confirm_participation(request=mock_request, data=data, db=mock_db)

        assert result["success"] is True
        assert mock_user.confirmed == "YES"
        assert mock_user.pandas_username == "tsponsor"
        assert mock_user.pandas_password == "existing_password"  # Password unchanged


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeclineParticipationRoute:
    """Test POST /api/public/confirm/decline endpoint."""

    async def test_decline_participation_missing_code(self, mocker):
        """Test declining without confirmation code."""
        mock_request = mocker.Mock()
        mock_db = mocker.AsyncMock()
        data = {"reason": "Schedule conflict"}

        with pytest.raises(Exception):
            await decline_participation(request=mock_request, data=data, db=mock_db)

    async def test_decline_participation_invalid_code(self, mocker):
        """Test declining with invalid code."""
        mock_request = mocker.Mock()
        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        data = {"confirmation_code": "invalid"}

        with pytest.raises(Exception):
            await decline_participation(request=mock_request, data=data, db=mock_db)

    async def test_decline_participation_already_declined(self, mocker):
        """Test declining when already declined."""
        mock_request = mocker.Mock()

        mock_user = Mock()
        mock_user.confirmed = "NO"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)

        data = {"confirmation_code": "code123"}

        with pytest.raises(Exception):
            await decline_participation(request=mock_request, data=data, db=mock_db)

    async def test_decline_participation_success_with_reason(self, mocker):
        """Test successful decline with reason."""
        mock_request = mocker.Mock()
        mock_request.client = mocker.Mock(host="192.168.1.1")
        mock_request.headers = {"user-agent": "TestBrowser"}

        mock_user = Mock()
        mock_user.id = 1
        mock_user.confirmed = "UNKNOWN"
        mock_user.first_name = "Test"
        mock_user.email = "test@test.com"

        mock_event = Mock()
        mock_event.id = 1
        mock_event.name = "CyberX 2026"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)
        mock_db.commit = mocker.AsyncMock()
        mock_db.refresh = mocker.AsyncMock()

        # Mock services
        mock_audit = mocker.Mock()
        mock_audit.log = mocker.AsyncMock()
        mocker.patch('app.api.routes.public.AuditService', return_value=mock_audit)

        mock_event_service = mocker.Mock()
        mock_event_service.get_current_event = mocker.AsyncMock(return_value=mock_event)
        mocker.patch('app.api.routes.public.EventService', return_value=mock_event_service)

        data = {
            "confirmation_code": "code123",
            "reason": "Schedule conflict"
        }

        result = await decline_participation(request=mock_request, data=data, db=mock_db)

        assert result["success"] is True
        assert "declined" in result["message"].lower()
        assert mock_user.confirmed == "NO"
        assert mock_user.decline_reason == "Schedule conflict"

    async def test_decline_participation_success_no_reason(self, mocker):
        """Test successful decline without reason."""
        mock_request = mocker.Mock()
        mock_request.client = mocker.Mock(host="192.168.1.1")
        mock_request.headers = {"user-agent": "TestBrowser"}

        mock_user = Mock()
        mock_user.id = 1
        mock_user.confirmed = "UNKNOWN"

        mock_event = Mock()
        mock_event.id = 1
        mock_event.name = "CyberX 2026"

        mock_db = mocker.AsyncMock()
        mock_result = mocker.Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = mocker.AsyncMock(return_value=mock_result)
        mock_db.commit = mocker.AsyncMock()
        mock_db.refresh = mocker.AsyncMock()

        # Mock services
        mock_audit = mocker.Mock()
        mock_audit.log = mocker.AsyncMock()
        mocker.patch('app.api.routes.public.AuditService', return_value=mock_audit)

        mock_event_service = mocker.Mock()
        mock_event_service.get_current_event = mocker.AsyncMock(return_value=mock_event)
        mocker.patch('app.api.routes.public.EventService', return_value=mock_event_service)

        data = {"confirmation_code": "code123"}

        result = await decline_participation(request=mock_request, data=data, db=mock_db)

        assert result["success"] is True
        assert mock_user.confirmed == "NO"
        assert mock_user.decline_reason is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetCountriesRoute:
    """Test GET /api/public/countries endpoint."""

    async def test_get_countries_returns_list(self, mocker):
        """Test that get_countries returns a list of countries."""
        # Mock the countries module
        mock_countries_list = [
            {"code": "US", "name": "United States", "flag": "🇺🇸"},
            {"code": "GB", "name": "United Kingdom", "flag": "🇬🇧"},
        ]
        mocker.patch('app.countries.get_countries_list', return_value=mock_countries_list)
        mocker.patch('app.countries.DEFAULT_COUNTRY', "US")

        result = await get_countries()

        assert "countries" in result
        assert "default" in result
        assert len(result["countries"]) == 2
        assert result["default"] == "US"
