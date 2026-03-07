"""Unit tests for permission constants and resolution logic."""
import pytest
from app.utils.permissions import (
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    get_permissions_for_role_string,
    resolve_permissions,
)


@pytest.mark.unit
class TestPermissionConstants:
    """Test permission constant definitions."""

    def test_all_permissions_count(self):
        """All 43 permission strings should be defined."""
        assert len(ALL_PERMISSIONS) == 43

    def test_admin_has_all_permissions(self):
        """Admin role should have all permissions."""
        assert ROLE_PERMISSIONS["admin"] == ALL_PERMISSIONS

    def test_sponsor_permission_count(self):
        """Sponsor role should have 11 permissions."""
        assert len(ROLE_PERMISSIONS["sponsor"]) == 11

    def test_invitee_permission_count(self):
        """Invitee role should have 7 permissions."""
        assert len(ROLE_PERMISSIONS["invitee"]) == 7

    def test_sponsor_is_superset_of_invitee(self):
        """Sponsor permissions should include all invitee permissions."""
        assert ROLE_PERMISSIONS["invitee"].issubset(ROLE_PERMISSIONS["sponsor"])

    def test_sponsor_has_participant_management(self):
        """Sponsor should have participant management permissions."""
        sponsor = ROLE_PERMISSIONS["sponsor"]
        assert "participants.view" in sponsor
        assert "participants.create" in sponsor
        assert "participants.edit" in sponsor
        assert "participants.invite" in sponsor

    def test_invitee_has_self_service_permissions(self):
        """Invitee should have self-service permissions."""
        invitee = ROLE_PERMISSIONS["invitee"]
        assert "instances.view" in invitee
        assert "instances.provision" in invitee
        assert "vpn.view" in invitee
        assert "vpn.request" in invitee
        assert "vpn.download" in invitee
        assert "certs.request" in invitee
        assert "certs.download" in invitee

    def test_all_permissions_are_strings(self):
        """All permissions should be non-empty strings."""
        for perm in ALL_PERMISSIONS:
            assert isinstance(perm, str)
            assert len(perm) > 0
            assert "." in perm  # All perms use dot notation

    def test_all_role_permissions_are_valid(self):
        """All role permissions should be in ALL_PERMISSIONS."""
        for role_name, perms in ROLE_PERMISSIONS.items():
            invalid = perms - ALL_PERMISSIONS
            assert not invalid, f"{role_name} has invalid permissions: {invalid}"


@pytest.mark.unit
class TestPermissionResolution:
    """Test resolve_permissions function."""

    def test_base_only(self):
        """Resolving with no overrides returns base."""
        base = {"events.view", "events.create"}
        result = resolve_permissions(base)
        assert result == {"events.view", "events.create"}

    def test_add_only(self):
        """Resolving with additions expands the set."""
        base = {"events.view"}
        result = resolve_permissions(base, add={"events.create"})
        assert result == {"events.view", "events.create"}

    def test_remove_only(self):
        """Resolving with removals shrinks the set."""
        base = {"events.view", "events.create", "events.edit"}
        result = resolve_permissions(base, remove={"events.edit"})
        assert result == {"events.view", "events.create"}

    def test_add_and_remove(self):
        """Resolving with both add and remove works correctly."""
        base = {"events.view", "events.create"}
        result = resolve_permissions(
            base,
            add={"events.edit", "events.delete"},
            remove={"events.create"},
        )
        assert result == {"events.view", "events.edit", "events.delete"}

    def test_remove_nonexistent_is_noop(self):
        """Removing a permission not in base is a no-op."""
        base = {"events.view"}
        result = resolve_permissions(base, remove={"events.delete"})
        assert result == {"events.view"}

    def test_add_duplicate_is_noop(self):
        """Adding a permission already in base is a no-op."""
        base = {"events.view"}
        result = resolve_permissions(base, add={"events.view"})
        assert result == {"events.view"}

    def test_empty_base(self):
        """Resolving with empty base returns just additions."""
        result = resolve_permissions(set(), add={"events.view"})
        assert result == {"events.view"}

    def test_does_not_mutate_input(self):
        """resolve_permissions should not mutate the input set."""
        base = {"events.view"}
        original = base.copy()
        resolve_permissions(base, add={"events.create"})
        assert base == original


@pytest.mark.unit
class TestLegacyFallback:
    """Test get_permissions_for_role_string function."""

    def test_admin_role_string(self):
        """Admin role string should return all permissions."""
        perms = get_permissions_for_role_string("admin")
        assert perms == ALL_PERMISSIONS

    def test_sponsor_role_string(self):
        """Sponsor role string should return sponsor permissions."""
        perms = get_permissions_for_role_string("sponsor")
        assert perms == ROLE_PERMISSIONS["sponsor"]

    def test_invitee_role_string(self):
        """Invitee role string should return invitee permissions."""
        perms = get_permissions_for_role_string("invitee")
        assert perms == ROLE_PERMISSIONS["invitee"]

    def test_unknown_role_string(self):
        """Unknown role string should return empty set."""
        perms = get_permissions_for_role_string("nonexistent")
        assert perms == set()

    def test_case_insensitive(self):
        """Role string lookup should be case-insensitive."""
        perms = get_permissions_for_role_string("ADMIN")
        assert perms == ALL_PERMISSIONS

    def test_returns_copy(self):
        """Should return a copy, not a reference to the original."""
        perms1 = get_permissions_for_role_string("invitee")
        perms1.add("fake.permission")
        perms2 = get_permissions_for_role_string("invitee")
        assert "fake.permission" not in perms2
