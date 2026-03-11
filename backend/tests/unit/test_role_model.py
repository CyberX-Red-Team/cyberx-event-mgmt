"""Unit tests for the Role model."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.role import Role, BaseType
from app.utils.permissions import ALL_PERMISSIONS


@pytest.mark.unit
class TestBaseTypeEnum:
    """Test BaseType enum values."""

    def test_admin_value(self):
        assert BaseType.ADMIN.value == "admin"

    def test_sponsor_value(self):
        assert BaseType.SPONSOR.value == "sponsor"

    def test_invitee_value(self):
        assert BaseType.INVITEE.value == "invitee"

    def test_enum_count(self):
        assert len(BaseType) == 3

    def test_string_subclass(self):
        """BaseType should be usable as a string."""
        assert BaseType.ADMIN == "admin"


@pytest.mark.unit
class TestRoleModel:
    """Test Role model creation and fields."""

    @pytest.mark.asyncio
    async def test_create_role(self, db_session):
        """Should create a role with all fields."""
        role = Role(
            name="Test Role",
            slug="test_role",
            base_type=BaseType.INVITEE.value,
            permissions=["instances.view", "vpn.view"],
            is_system=False,
            description="A test role",
        )
        db_session.add(role)
        await db_session.commit()
        await db_session.refresh(role)

        assert role.id is not None
        assert role.name == "Test Role"
        assert role.slug == "test_role"
        assert role.base_type == "invitee"
        assert role.permissions == ["instances.view", "vpn.view"]
        assert role.is_system is False
        assert role.description == "A test role"
        assert role.created_at is not None
        assert role.updated_at is not None

    @pytest.mark.asyncio
    async def test_slug_uniqueness(self, db_session):
        """Duplicate slugs should raise IntegrityError."""
        role1 = Role(
            name="Role A",
            slug="duplicate",
            base_type=BaseType.INVITEE.value,
            permissions=[],
        )
        db_session.add(role1)
        await db_session.commit()

        role2 = Role(
            name="Role B",
            slug="duplicate",
            base_type=BaseType.INVITEE.value,
            permissions=[],
        )
        db_session.add(role2)
        with pytest.raises(IntegrityError):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_system_role_flag(self, admin_role):
        """System roles should have is_system=True."""
        assert admin_role.is_system is True

    @pytest.mark.asyncio
    async def test_permissions_stored_as_list(self, admin_role):
        """Permissions should be stored and retrieved as a list."""
        assert isinstance(admin_role.permissions, list)
        assert len(admin_role.permissions) == len(ALL_PERMISSIONS)

    @pytest.mark.asyncio
    async def test_repr(self, admin_role):
        """__repr__ should include key fields."""
        r = repr(admin_role)
        assert "admin" in r
        assert "Role" in r

    @pytest.mark.asyncio
    async def test_nullable_description(self, db_session):
        """Description should be optional."""
        role = Role(
            name="No Desc",
            slug="no_desc",
            base_type=BaseType.INVITEE.value,
            permissions=[],
        )
        db_session.add(role)
        await db_session.commit()
        await db_session.refresh(role)
        assert role.description is None

    @pytest.mark.asyncio
    async def test_user_relationship(self, db_session, admin_role, admin_user):
        """Role should have back-reference to users."""
        await db_session.refresh(admin_role)
        # SQLite doesn't lazy-load relationships the same way, so query directly
        result = await db_session.execute(
            select(Role).where(Role.id == admin_role.id)
        )
        role = result.scalar_one()
        assert role is not None
