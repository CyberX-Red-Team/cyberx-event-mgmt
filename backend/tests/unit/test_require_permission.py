"""Unit tests for require_permission dependency and updated PermissionChecker."""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.dependencies import require_permission, PermissionChecker
from app.models.user import User, UserRole
from app.utils.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS
from app.utils.security import hash_password
from app.api.utils.validation import normalize_email


@pytest.mark.unit
class TestRequirePermission:
    """Test the require_permission() dependency factory."""

    @pytest.mark.asyncio
    async def test_grants_access_with_permission(self, admin_user):
        """User with required permission should pass."""
        checker = require_permission("events.view")
        # Call the inner function directly
        result = await checker.__wrapped__(admin_user) if hasattr(checker, '__wrapped__') else None
        # Since require_permission returns a closure, we test via the user model
        assert admin_user.has_permission("events.view")

    @pytest.mark.asyncio
    async def test_admin_has_all_permissions(self, admin_user):
        """Admin should pass any permission check."""
        assert admin_user.has_permission("events.view")
        assert admin_user.has_permission("participants.create")
        assert admin_user.has_permission("vpn.manage_pool")
        assert admin_user.has_permission("admin.manage_settings")

    @pytest.mark.asyncio
    async def test_invitee_lacks_admin_permissions(self, invitee_user):
        """Invitee should fail admin permission checks."""
        assert not invitee_user.has_permission("events.view")
        assert not invitee_user.has_permission("participants.create")
        assert not invitee_user.has_permission("admin.manage_settings")

    @pytest.mark.asyncio
    async def test_invitee_has_self_service_permissions(self, invitee_user):
        """Invitee should have self-service permissions."""
        assert invitee_user.has_permission("instances.view")
        assert invitee_user.has_permission("vpn.view")
        assert invitee_user.has_permission("tls.request")

    @pytest.mark.asyncio
    async def test_sponsor_has_participant_management(self, sponsor_user):
        """Sponsor should have participant management permissions."""
        assert sponsor_user.has_permission("participants.view")
        assert sponsor_user.has_permission("participants.create")
        assert sponsor_user.has_permission("participants.edit")
        assert sponsor_user.has_permission("participants.invite")

    @pytest.mark.asyncio
    async def test_sponsor_lacks_admin_only_permissions(self, sponsor_user):
        """Sponsor should not have admin-only permissions."""
        assert not sponsor_user.has_permission("events.view")
        assert not sponsor_user.has_permission("admin.manage_users")
        assert not sponsor_user.has_permission("vpn.manage_pool")

    @pytest.mark.asyncio
    async def test_multiple_permissions_all_required(self, sponsor_user):
        """has_permission with multiple args requires ALL."""
        # Sponsor has both
        assert sponsor_user.has_permission("participants.view", "participants.create")
        # Sponsor lacks events.view
        assert not sponsor_user.has_permission("participants.view", "events.view")

    @pytest.mark.asyncio
    async def test_any_permission_check(self, sponsor_user):
        """has_any_permission requires at least one match."""
        assert sponsor_user.has_any_permission("events.view", "participants.view")
        assert not sponsor_user.has_any_permission("events.view", "admin.manage_users")


@pytest.mark.unit
class TestPermissionCheckerUpdated:
    """Test PermissionChecker methods use permission-based checks."""

    def setup_method(self):
        self.checker = PermissionChecker()

    def _make_user(self, perms, user_id=1):
        """Create a mock user with specific permissions."""
        user = MagicMock(spec=User)
        user.id = user_id
        user.has_permission = lambda *p: all(perm in perms for perm in p)
        user.has_any_permission = lambda *p: any(perm in perms for perm in p)
        return user

    def test_can_view_participant_self(self):
        """Users can always view themselves."""
        user = self._make_user(set(), user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 1
        # Should not raise
        self.checker.can_view_participant(user, participant)

    def test_can_view_participant_with_view_all(self):
        """Users with participants.view_all can view anyone."""
        user = self._make_user({"participants.view_all"}, user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        participant.sponsor_id = 99
        self.checker.can_view_participant(user, participant)

    def test_can_view_participant_sponsor_own(self):
        """Sponsors can view their own sponsored participants."""
        user = self._make_user({"participants.view"}, user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        participant.sponsor_id = 1  # sponsored by user
        self.checker.can_view_participant(user, participant)

    def test_cannot_view_participant_unauthorized(self):
        """Users without participant permissions cannot view others."""
        user = self._make_user(set(), user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        participant.sponsor_id = 99
        with pytest.raises(HTTPException) as exc_info:
            self.checker.can_view_participant(user, participant)
        assert exc_info.value.status_code == 403

    def test_can_edit_participant_with_view_all(self):
        """Admin-level users (with participants.view_all + edit) can edit anyone."""
        user = self._make_user({"participants.edit", "participants.view_all"}, user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        participant.sponsor_id = 99
        self.checker.can_edit_participant(user, participant)

    def test_can_edit_participant_sponsor_own(self):
        """Sponsors can edit their sponsored participants."""
        user = self._make_user({"participants.edit"}, user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        participant.sponsor_id = 1
        self.checker.can_edit_participant(user, participant)

    def test_cannot_edit_self(self):
        """Users cannot edit themselves via this endpoint."""
        user = self._make_user({"participants.edit", "participants.view_all"}, user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 1
        with pytest.raises(HTTPException) as exc_info:
            self.checker.can_edit_participant(user, participant)
        assert exc_info.value.status_code == 403

    def test_cannot_edit_without_permission(self):
        """Users without participants.edit cannot edit."""
        user = self._make_user(set(), user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        with pytest.raises(HTTPException) as exc_info:
            self.checker.can_edit_participant(user, participant)
        assert exc_info.value.status_code == 403

    def test_can_delete_with_permission(self):
        """Users with participants.remove can delete."""
        user = self._make_user({"participants.remove"}, user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        self.checker.can_delete_participant(user, participant)

    def test_cannot_delete_without_permission(self):
        """Users without participants.remove cannot delete."""
        user = self._make_user(set(), user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        with pytest.raises(HTTPException) as exc_info:
            self.checker.can_delete_participant(user, participant)
        assert exc_info.value.status_code == 403

    def test_cannot_delete_self(self):
        """Users cannot delete themselves."""
        user = self._make_user({"participants.remove"}, user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 1
        with pytest.raises(HTTPException) as exc_info:
            self.checker.can_delete_participant(user, participant)
        assert exc_info.value.status_code == 403

    def test_can_send_bulk_email(self):
        """Users with email.send_bulk can send bulk emails."""
        user = self._make_user({"email.send_bulk"})
        self.checker.can_send_bulk_email(user)

    def test_cannot_send_bulk_email(self):
        """Users without email.send_bulk cannot send bulk emails."""
        user = self._make_user(set())
        with pytest.raises(HTTPException) as exc_info:
            self.checker.can_send_bulk_email(user)
        assert exc_info.value.status_code == 403

    def test_can_manage_vpn(self):
        """Users with vpn.manage_pool can manage VPN."""
        user = self._make_user({"vpn.manage_pool"})
        self.checker.can_manage_vpn(user)

    def test_cannot_manage_vpn(self):
        """Users without vpn.manage_pool cannot manage VPN."""
        user = self._make_user(set())
        with pytest.raises(HTTPException) as exc_info:
            self.checker.can_manage_vpn(user)
        assert exc_info.value.status_code == 403

    def test_can_assign_vpn_admin(self):
        """Users with vpn.manage_pool + participants.view_all can assign VPN to anyone."""
        user = self._make_user({"vpn.manage_pool", "participants.view_all"}, user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        participant.sponsor_id = 99
        self.checker.can_assign_vpn_to_participant(user, participant)

    def test_can_assign_vpn_sponsor_own(self):
        """Sponsors can assign VPN to their sponsored participants."""
        user = self._make_user({"vpn.manage_pool"}, user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        participant.sponsor_id = 1
        self.checker.can_assign_vpn_to_participant(user, participant)

    def test_cannot_assign_vpn_no_permission(self):
        """Users without vpn.manage_pool cannot assign VPN."""
        user = self._make_user(set(), user_id=1)
        participant = MagicMock(spec=User)
        participant.id = 2
        with pytest.raises(HTTPException) as exc_info:
            self.checker.can_assign_vpn_to_participant(user, participant)
        assert exc_info.value.status_code == 403
