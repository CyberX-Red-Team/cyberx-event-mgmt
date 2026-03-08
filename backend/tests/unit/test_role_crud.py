"""Unit tests for role CRUD operations and schemas."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role, BaseType
from app.models.user import User, UserRole
from app.schemas.role import (
    RoleCreate, RoleUpdate, PermissionOverrideUpdate, RoleAssignRequest, slugify,
)
from app.utils.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS
from app.utils.security import hash_password
from app.api.utils.validation import normalize_email


@pytest.mark.unit
class TestSlugify:
    """Test slug generation."""

    def test_basic_slug(self):
        assert slugify("Lab Manager") == "lab-manager"

    def test_special_chars(self):
        assert slugify("Senior Admin!@#") == "senior-admin"

    def test_multiple_spaces(self):
        assert slugify("  multiple   spaces  ") == "multiple-spaces"

    def test_already_slug(self):
        assert slugify("already-a-slug") == "already-a-slug"

    def test_uppercase(self):
        assert slugify("UPPERCASE") == "uppercase"


@pytest.mark.unit
class TestRoleSchemas:
    """Test role Pydantic schemas."""

    def test_role_create_valid(self):
        data = RoleCreate(
            name="Lab Manager",
            base_type="sponsor",
            permissions=["participants.view", "participants.create"],
        )
        assert data.name == "Lab Manager"
        assert data.base_type == "sponsor"
        assert data.permissions == ["participants.create", "participants.view"]  # sorted

    def test_role_create_invalid_permission(self):
        with pytest.raises(ValueError, match="Invalid permissions"):
            RoleCreate(
                name="Bad Role",
                base_type="invitee",
                permissions=["nonexistent.perm"],
            )

    def test_role_create_invalid_base_type(self):
        with pytest.raises(ValueError):
            RoleCreate(
                name="Bad Role",
                base_type="superadmin",
                permissions=[],
            )

    def test_role_update_valid(self):
        data = RoleUpdate(
            name="Updated Name",
            permissions=["events.view"],
        )
        assert data.name == "Updated Name"
        assert data.permissions == ["events.view"]

    def test_role_update_none_permissions(self):
        data = RoleUpdate(name="Just Name")
        assert data.permissions is None

    def test_role_update_invalid_permission(self):
        with pytest.raises(ValueError, match="Invalid permissions"):
            RoleUpdate(permissions=["fake.perm"])

    def test_permission_override_valid(self):
        data = PermissionOverrideUpdate(
            add=["events.view", "events.create"],
            remove=["vpn.download"],
        )
        assert data.add == ["events.create", "events.view"]  # sorted, deduped
        assert data.remove == ["vpn.download"]

    def test_permission_override_invalid(self):
        with pytest.raises(ValueError, match="Invalid permissions"):
            PermissionOverrideUpdate(add=["bad.perm"])

    def test_role_assign_request(self):
        data = RoleAssignRequest(role_id=5)
        assert data.role_id == 5


@pytest.mark.unit
class TestRoleCRUD:
    """Test role CRUD operations at the model level."""

    @pytest.mark.asyncio
    async def test_list_system_roles(self, db_session, admin_role, sponsor_role, invitee_role):
        """Should list all 3 system roles."""
        result = await db_session.execute(select(Role).where(Role.is_system == True))
        roles = result.scalars().all()
        assert len(roles) == 3
        slugs = {r.slug for r in roles}
        assert slugs == {"admin", "sponsor", "invitee"}

    @pytest.mark.asyncio
    async def test_create_custom_role(self, db_session):
        """Should create a custom role."""
        role = Role(
            name="Lab Manager",
            slug="lab-manager",
            base_type=BaseType.SPONSOR.value,
            permissions=["participants.view", "participants.create", "instances.view"],
            is_system=False,
            description="Manages lab participants",
        )
        db_session.add(role)
        await db_session.commit()
        await db_session.refresh(role)

        assert role.id is not None
        assert role.name == "Lab Manager"
        assert role.slug == "lab-manager"
        assert role.base_type == "sponsor"
        assert not role.is_system
        assert len(role.permissions) == 3

    @pytest.mark.asyncio
    async def test_custom_role_unique_slug(self, db_session):
        """Should enforce unique slug constraint."""
        from sqlalchemy.exc import IntegrityError

        role1 = Role(
            name="Custom A",
            slug="custom-role",
            base_type="invitee",
            permissions=[],
            is_system=False,
        )
        db_session.add(role1)
        await db_session.commit()

        role2 = Role(
            name="Custom B",
            slug="custom-role",
            base_type="invitee",
            permissions=[],
            is_system=False,
        )
        db_session.add(role2)
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_delete_custom_role(self, db_session):
        """Should delete a custom role."""
        role = Role(
            name="Temp Role",
            slug="temp-role",
            base_type="invitee",
            permissions=[],
            is_system=False,
        )
        db_session.add(role)
        await db_session.commit()
        role_id = role.id

        await db_session.delete(role)
        await db_session.commit()

        result = await db_session.execute(select(Role).where(Role.id == role_id))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_assign_role_to_user(self, db_session, invitee_role):
        """Should assign a role to a user and resolve permissions."""
        custom_role = Role(
            name="Enhanced Invitee",
            slug="enhanced-invitee",
            base_type="invitee",
            permissions=sorted(list(ROLE_PERMISSIONS["invitee"]) + ["events.view"]),
            is_system=False,
        )
        db_session.add(custom_role)
        await db_session.commit()
        await db_session.refresh(custom_role)

        user = User(
            email="enhanced@test.com",
            email_normalized=normalize_email("enhanced@test.com"),
            first_name="Enhanced",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value,
            role_id=custom_role.id,
            is_active=True,
            confirmed="YES",
            password_hash=hash_password("test123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Eagerly load role_obj
        result = await db_session.execute(
            select(User).where(User.id == user.id)
        )
        user = result.scalar_one()
        # Manually set role_obj for unit test (normally eager-loaded)
        user.role_obj = custom_role

        perms = user.get_effective_permissions()
        assert "events.view" in perms
        assert "instances.view" in perms  # from invitee base

    @pytest.mark.asyncio
    async def test_delete_role_reassign_users(self, db_session, invitee_role):
        """Deleting a role should allow reassigning users to fallback."""
        custom_role = Role(
            name="Deletable Role",
            slug="deletable-role",
            base_type="invitee",
            permissions=["instances.view"],
            is_system=False,
        )
        db_session.add(custom_role)
        await db_session.commit()
        await db_session.refresh(custom_role)

        user = User(
            email="reassign@test.com",
            email_normalized=normalize_email("reassign@test.com"),
            first_name="Reassign",
            last_name="User",
            country="USA",
            role=UserRole.INVITEE.value,
            role_id=custom_role.id,
            is_active=True,
            confirmed="YES",
            password_hash=hash_password("test123"),
        )
        db_session.add(user)
        await db_session.commit()
        user_id = user.id

        # Reassign user to invitee_role before deleting custom_role
        user.role_id = invitee_role.id
        user.permission_overrides = {}
        await db_session.commit()

        # Now delete the custom role
        await db_session.delete(custom_role)
        await db_session.commit()

        # User should still exist with invitee role
        result = await db_session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        assert user.role_id == invitee_role.id


@pytest.mark.unit
class TestPermissionOverrides:
    """Test permission override operations."""

    @pytest.mark.asyncio
    async def test_set_overrides(self, db_session, invitee_role):
        """Should set permission overrides on a user."""
        user = User(
            email="overrides@test.com",
            email_normalized=normalize_email("overrides@test.com"),
            first_name="Override",
            last_name="Test",
            country="USA",
            role=UserRole.INVITEE.value,
            role_id=invitee_role.id,
            is_active=True,
            confirmed="YES",
            password_hash=hash_password("test123"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        # Set overrides
        user.permission_overrides = {
            "add": ["events.view"],
            "remove": ["vpn.download"],
        }
        await db_session.commit()
        await db_session.refresh(user)

        # Manually set role_obj for unit test
        user.role_obj = invitee_role

        perms = user.get_effective_permissions()
        assert "events.view" in perms
        assert "vpn.download" not in perms
        assert "instances.view" in perms  # still has base perm

    @pytest.mark.asyncio
    async def test_clear_overrides(self, db_session, invitee_role):
        """Should clear permission overrides."""
        user = User(
            email="clear-overrides@test.com",
            email_normalized=normalize_email("clear-overrides@test.com"),
            first_name="Clear",
            last_name="Test",
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

        # Clear overrides
        user.permission_overrides = {}
        await db_session.commit()
        await db_session.refresh(user)

        # Manually set role_obj
        user.role_obj = invitee_role

        perms = user.get_effective_permissions()
        assert "events.view" not in perms
        assert perms == set(ROLE_PERMISSIONS["invitee"])
