"""Seed required roles on startup (idempotent)."""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.role import Role, BaseType
from app.utils.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS

logger = logging.getLogger(__name__)

# Built-in roles that must exist for the application to function.
# Only creates missing roles — updates system role permissions to stay in sync.
REQUIRED_ROLES = [
    {
        "name": "Admin",
        "slug": "admin",
        "base_type": BaseType.ADMIN.value,
        "permissions": sorted(ALL_PERMISSIONS),
        "is_system": True,
        "description": "Full system access — all permissions enabled",
    },
    {
        "name": "Sponsor",
        "slug": "sponsor",
        "base_type": BaseType.SPONSOR.value,
        "permissions": sorted(ROLE_PERMISSIONS["sponsor"]),
        "is_system": True,
        "description": "Can manage sponsored participants and their resources",
    },
    {
        "name": "Invitee",
        "slug": "invitee",
        "base_type": BaseType.INVITEE.value,
        "permissions": sorted(ROLE_PERMISSIONS["invitee"]),
        "is_system": True,
        "description": "Standard participant access — can manage own resources",
    },
]


async def seed_required_roles(session: AsyncSession) -> None:
    """Create any missing required roles. Updates system role permissions."""
    for role_data in REQUIRED_ROLES:
        result = await session.execute(
            select(Role).where(Role.slug == role_data["slug"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update system role permissions to stay in sync with code
            if existing.is_system:
                existing.permissions = role_data["permissions"]
                existing.description = role_data["description"]
            continue

        logger.info("  Seeding missing role: %s", role_data["slug"])
        session.add(Role(**role_data))

    await session.commit()
