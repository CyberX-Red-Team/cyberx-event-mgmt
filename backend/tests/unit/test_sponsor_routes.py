"""Unit tests for sponsor API routes.

Tests route-level logic for sponsor invitee delete, including ownership checks,
confirmed-event guards, and permission enforcement.
All service dependencies are mocked to isolate route behavior.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.routes.sponsor import delete_my_invitee
from app.models.user import User, UserRole


def _make_sponsor(user_id=1, perms=None):
    """Create a mock sponsor user with specific permissions."""
    if perms is None:
        perms = {"participants.remove", "participants.view"}
    user = MagicMock(spec=User)
    user.id = user_id
    user.has_permission = lambda *p: all(perm in perms for perm in p)
    user.has_any_permission = lambda *p: any(perm in perms for perm in p)
    return user


def _make_invitee(invitee_id=10, sponsor_id=1, participation_status=None):
    """Create a mock invitee user with optional event participation."""
    invitee = MagicMock(spec=User)
    invitee.id = invitee_id
    invitee.sponsor_id = sponsor_id
    invitee.email = "invitee@test.com"
    invitee.first_name = "Test"
    invitee.last_name = "Invitee"

    # Mock get_current_event_participation
    if participation_status:
        participation = MagicMock()
        participation.status = participation_status
        invitee.get_current_event_participation = AsyncMock(return_value=participation)
    else:
        invitee.get_current_event_participation = AsyncMock(return_value=None)

    return invitee


@pytest.mark.unit
@pytest.mark.asyncio
class TestSponsorDeleteInvitee:
    """Test sponsor delete invitee route."""

    async def test_delete_own_pending_invitee(self):
        """Sponsor can delete their own invitee who has not confirmed."""
        sponsor = _make_sponsor(user_id=1)
        invitee = _make_invitee(invitee_id=10, sponsor_id=1, participation_status="invited")

        service = MagicMock()
        service.get_participant = AsyncMock(return_value=invitee)
        service.delete_participant = AsyncMock(return_value=True)

        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        db = AsyncMock()

        with patch("app.api.routes.sponsor.extract_client_metadata", return_value=("127.0.0.1", "test")), \
             patch("app.services.audit_service.AuditService", autospec=True) as MockAudit:
            mock_audit_instance = MockAudit.return_value
            mock_audit_instance.log_user_delete = AsyncMock()

            result = await delete_my_invitee(
                invitee_id=10,
                request=request,
                db=db,
                current_user=sponsor,
                service=service
            )

        assert result == {"message": "Invitee deleted successfully"}
        service.delete_participant.assert_called_once_with(10)

    async def test_delete_own_declined_invitee(self):
        """Sponsor can delete their own invitee who has declined."""
        sponsor = _make_sponsor(user_id=1)
        invitee = _make_invitee(invitee_id=10, sponsor_id=1, participation_status="declined")

        service = MagicMock()
        service.get_participant = AsyncMock(return_value=invitee)
        service.delete_participant = AsyncMock(return_value=True)

        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        db = AsyncMock()

        with patch("app.api.routes.sponsor.extract_client_metadata", return_value=("127.0.0.1", "test")), \
             patch("app.services.audit_service.AuditService", autospec=True) as MockAudit:
            mock_audit_instance = MockAudit.return_value
            mock_audit_instance.log_user_delete = AsyncMock()

            result = await delete_my_invitee(
                invitee_id=10,
                request=request,
                db=db,
                current_user=sponsor,
                service=service
            )

        assert result == {"message": "Invitee deleted successfully"}

    async def test_delete_own_invitee_no_participation(self):
        """Sponsor can delete their own invitee with no event participation."""
        sponsor = _make_sponsor(user_id=1)
        invitee = _make_invitee(invitee_id=10, sponsor_id=1, participation_status=None)

        service = MagicMock()
        service.get_participant = AsyncMock(return_value=invitee)
        service.delete_participant = AsyncMock(return_value=True)

        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        db = AsyncMock()

        with patch("app.api.routes.sponsor.extract_client_metadata", return_value=("127.0.0.1", "test")), \
             patch("app.services.audit_service.AuditService", autospec=True) as MockAudit:
            mock_audit_instance = MockAudit.return_value
            mock_audit_instance.log_user_delete = AsyncMock()

            result = await delete_my_invitee(
                invitee_id=10,
                request=request,
                db=db,
                current_user=sponsor,
                service=service
            )

        assert result == {"message": "Invitee deleted successfully"}

    async def test_cannot_delete_confirmed_invitee(self):
        """Sponsor cannot delete an invitee who has confirmed for the current event."""
        sponsor = _make_sponsor(user_id=1)
        invitee = _make_invitee(invitee_id=10, sponsor_id=1, participation_status="confirmed")

        service = MagicMock()
        service.get_participant = AsyncMock(return_value=invitee)

        request = MagicMock()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await delete_my_invitee(
                invitee_id=10,
                request=request,
                db=db,
                current_user=sponsor,
                service=service
            )

        assert exc_info.value.status_code == 403
        assert "confirmed" in exc_info.value.detail.lower()
        service.delete_participant.assert_not_called()

    async def test_cannot_delete_other_sponsors_invitee(self):
        """Sponsor cannot delete an invitee belonging to another sponsor."""
        sponsor = _make_sponsor(user_id=1)
        invitee = _make_invitee(invitee_id=10, sponsor_id=99)

        service = MagicMock()
        service.get_participant = AsyncMock(return_value=invitee)

        request = MagicMock()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await delete_my_invitee(
                invitee_id=10,
                request=request,
                db=db,
                current_user=sponsor,
                service=service
            )

        assert exc_info.value.status_code == 404
        service.delete_participant.assert_not_called()

    async def test_cannot_delete_nonexistent_invitee(self):
        """Deleting a nonexistent invitee returns 404."""
        sponsor = _make_sponsor(user_id=1)

        service = MagicMock()
        service.get_participant = AsyncMock(return_value=None)

        request = MagicMock()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await delete_my_invitee(
                invitee_id=999,
                request=request,
                db=db,
                current_user=sponsor,
                service=service
            )

        assert exc_info.value.status_code == 404
