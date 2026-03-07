"""Unit tests for User permission methods."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.utils.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS
from app.utils.security import hash_password
from app.api.utils.validation import normalize_email


@pytest.mark.unit
class TestGetEffectivePermissions:
    """Test User.get_effective_permissions()."""

    @pytest.mark.asyncio
    async def test_admin_has_all_permissions(self, admin_user):
        """Admin user should have all 38 permissions."""
        perms = admin_user.get_effective_permissions()
        assert perms == ALL_PERMISSIONS

    @pytest.mark.asyncio
    async def test_sponsor_permissions(self, sponsor_user):
        """Sponsor user should have sponsor permissions."""
        perms = sponsor_user.get_effective_permissions()
        assert perms == ROLE_PERMISSIONS["sponsor"]

    @pytest.mark.asyncio
    async def test_invitee_permissions(self, invitee_user):
        """Invitee user should have invitee permissions."""
        perms = invitee_user.get_effective_permissions()
        assert perms == ROLE_PERMISSIONS["invitee"]

    @pytest.mark.asyncio
    async def test_override_add(self, db_session, invitee_role):
        """Permission overrides should add permissions."""
        user = User(
            email="override-add@test.com",
            email_normalized=normalize_email("override-add@test.com"),
            first_name="Override",
            last_name="Add",
            country="USA",
            role=UserRole.INVITEE.value,
            role_id=invitee_role.id,
            is_active=True,
            confirmed="YES",
            password_hash=hash_password("test123"),
            permission_overrides={"add": ["events.view"]},
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        perms = user.get_effective_permissions()
        assert "events.view" in perms
        # Still has base invitee permissions
        assert "instances.view" in perms

    @pytest.mark.asyncio
    async def test_override_remove(self, db_session, invitee_role):
        """Permission overrides should remove permissions."""
        user = User(
            email="override-remove@test.com",
            email_normalized=normalize_email("override-remove@test.com"),
            first_name="Override",
            last_name="Remove",
            country="USA",
            role=UserRole.INVITEE.value,
            role_id=invitee_role.id,
            is_active=True,
            confirmed="YES",
            password_hash=hash_password("test123"),
            permission_overrides={"remove": ["vpn.download"]},
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        perms = user.get_effective_permissions()
        assert "vpn.download" not in perms
        # Still has other invitee permissions
        assert "instances.view" in perms

    @pytest.mark.asyncio
    async def test_override_add_and_remove(self, db_session, invitee_role):
        """Both add and remove overrides should work together."""
        user = User(
            email="override-both@test.com",
            email_normalized=normalize_email("override-both@test.com"),
            first_name="Override",
            last_name="Both",
            country="USA",
            role=UserRole.INVITEE.value,
            role_id=invitee_role.id,
            is_active=True,
            confirmed="YES",
            password_hash=hash_password("test123"),
            permission_overrides={
                "add": ["events.view", "events.create"],
                "remove": ["vpn.download", "certs.download"],
            },
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        perms = user.get_effective_permissions()
        assert "events.view" in perms
        assert "events.create" in perms
        assert "vpn.download" not in perms
        assert "certs.download" not in perms
        assert "instances.view" in perms

    @pytest.mark.asyncio
    async def test_no_overrides(self, invitee_user):
        """User with no overrides should get base role permissions."""
        perms = invitee_user.get_effective_permissions()
        assert perms == ROLE_PERMISSIONS["invitee"]

    @pytest.mark.asyncio
    async def test_returns_set(self, admin_user):
        """Should return a set."""
        perms = admin_user.get_effective_permissions()
        assert isinstance(perms, set)


@pytest.mark.unit
class TestLegacyFallback:
    """Test get_effective_permissions with legacy role string (no role_obj)."""

    @pytest.mark.asyncio
    async def test_fallback_sponsor(self, db_session):
        """User without role_obj falls back to role string."""
        user = User(
            email="legacy-sponsor@test.com",
            email_normalized=normalize_email("legacy-sponsor@test.com"),
            first_name="Legacy",
            last_name="Sponsor",
            country="USA",
            role=UserRole.SPONSOR.value,
            is_active=True,
            confirmed="YES",
            password_hash=hash_password("test123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        perms = user.get_effective_permissions()
        assert perms == ROLE_PERMISSIONS["sponsor"]

    @pytest.mark.asyncio
    async def test_fallback_admin(self, db_session):
        """Admin fallback should return all permissions."""
        user = User(
            email="legacy-admin@test.com",
            email_normalized=normalize_email("legacy-admin@test.com"),
            first_name="Legacy",
            last_name="Admin",
            country="USA",
            role=UserRole.ADMIN.value,
            is_admin=True,
            is_active=True,
            confirmed="YES",
            password_hash=hash_password("test123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        perms = user.get_effective_permissions()
        assert perms == ALL_PERMISSIONS

    @pytest.mark.asyncio
    async def test_fallback_no_role(self, db_session):
        """User with no role_obj defaults to invitee via role column default."""
        user = User(
            email="no-role@test.com",
            email_normalized=normalize_email("no-role@test.com"),
            first_name="No",
            last_name="Role",
            country="USA",
            is_active=True,
            confirmed="YES",
            password_hash=hash_password("test123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # role column defaults to "invitee", so legacy fallback returns invitee perms
        perms = user.get_effective_permissions()
        assert perms == ROLE_PERMISSIONS["invitee"]


@pytest.mark.unit
class TestHasPermission:
    """Test User.has_permission() and has_any_permission()."""

    @pytest.mark.asyncio
    async def test_has_single_permission(self, admin_user):
        """Admin should have any single permission."""
        assert admin_user.has_permission("events.view") is True

    @pytest.mark.asyncio
    async def test_has_multiple_permissions(self, admin_user):
        """Admin should have multiple permissions checked at once."""
        assert admin_user.has_permission("events.view", "events.create", "events.edit") is True

    @pytest.mark.asyncio
    async def test_missing_permission(self, invitee_user):
        """Invitee should not have admin permissions."""
        assert invitee_user.has_permission("events.view") is False

    @pytest.mark.asyncio
    async def test_partial_permissions_fails(self, invitee_user):
        """has_permission should fail if ANY permission is missing."""
        assert invitee_user.has_permission("instances.view", "events.view") is False

    @pytest.mark.asyncio
    async def test_has_any_permission_match(self, invitee_user):
        """has_any_permission should pass if at least one matches."""
        assert invitee_user.has_any_permission("events.view", "instances.view") is True

    @pytest.mark.asyncio
    async def test_has_any_permission_no_match(self, invitee_user):
        """has_any_permission should fail if none match."""
        assert invitee_user.has_any_permission("events.view", "events.create") is False

    @pytest.mark.asyncio
    async def test_has_permission_empty(self, admin_user):
        """has_permission with no args should return True (vacuous truth)."""
        assert admin_user.has_permission() is True

    @pytest.mark.asyncio
    async def test_has_any_permission_empty(self, invitee_user):
        """has_any_permission with no args should return False."""
        assert invitee_user.has_any_permission() is False
