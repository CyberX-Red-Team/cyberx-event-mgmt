"""Admin API routes for role management."""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.dependencies import get_db, require_permission
from app.models.role import Role
from app.models.user import User
from app.schemas.role import (
    RoleResponse, RoleCreate, RoleUpdate, PermissionGroup, slugify,
)
from app.utils.permissions import ALL_PERMISSIONS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/roles", tags=["Admin Roles"])

# Permission categories for the UI grid
PERMISSION_CATEGORIES = [
    ("Events", ["events.view", "events.create", "events.edit", "events.delete"]),
    ("Participants", [
        "participants.view", "participants.view_all", "participants.create",
        "participants.edit", "participants.remove", "participants.invite",
    ]),
    ("Instances", [
        "instances.view", "instances.view_all", "instances.provision",
        "instances.delete", "instances.manage_agent", "instances.sync_status",
    ]),
    ("VPN", ["vpn.view", "vpn.request", "vpn.download", "vpn.manage_pool"]),
    ("Email", [
        "email.view", "email.send", "email.send_bulk",
        "email.manage_templates", "email.manage_queue", "email.manage_workflows",
    ]),
    ("Certificates", ["certs.request", "certs.download", "cpe.manage", "tls.manage"]),
    ("Cloud Infrastructure", ["cloud.manage_providers", "cloud.manage_templates", "cloud.manage_images"]),
    ("Licenses", ["licenses.view", "licenses.manage"]),
    ("Participant Actions", ["actions.view", "actions.manage"]),
    ("Keycloak", ["keycloak.manage"]),
    ("Admin / System", [
        "admin.manage_users", "admin.manage_roles", "admin.view_audit_log",
        "admin.manage_settings", "scheduler.view",
    ]),
]


async def _build_role_response(role: Role, db: AsyncSession) -> dict:
    """Build a role response dict with user count."""
    count_result = await db.execute(
        select(func.count()).where(User.role_id == role.id)
    )
    user_count = count_result.scalar() or 0
    return {
        "id": role.id,
        "name": role.name,
        "slug": role.slug,
        "base_type": role.base_type,
        "permissions": sorted(role.permissions or []),
        "is_system": role.is_system,
        "description": role.description,
        "user_count": user_count,
        "created_at": role.created_at,
        "updated_at": role.updated_at,
    }


@router.get("/permissions")
async def list_permissions(
    current_user: User = Depends(require_permission("admin.manage_roles")),
):
    """List all permissions grouped by category."""
    return [
        PermissionGroup(category=cat, permissions=perms)
        for cat, perms in PERMISSION_CATEGORIES
    ]


@router.get("/")
async def list_roles(
    current_user: User = Depends(require_permission("admin.manage_roles")),
    db: AsyncSession = Depends(get_db),
):
    """List all roles with user counts."""
    result = await db.execute(select(Role).order_by(Role.is_system.desc(), Role.name))
    roles = result.scalars().all()

    return [await _build_role_response(r, db) for r in roles]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_role(
    data: RoleCreate,
    current_user: User = Depends(require_permission("admin.manage_roles")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new custom role."""
    slug = slugify(data.name)
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name must produce a valid slug",
        )

    # Check slug uniqueness
    existing = await db.execute(select(Role).where(Role.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A role with slug '{slug}' already exists",
        )

    role = Role(
        name=data.name.strip(),
        slug=slug,
        base_type=data.base_type,
        permissions=data.permissions,
        is_system=False,
        description=data.description,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)

    logger.info("Role '%s' created by user %d", role.name, current_user.id)
    return await _build_role_response(role, db)


@router.get("/{role_id}")
async def get_role(
    role_id: int,
    current_user: User = Depends(require_permission("admin.manage_roles")),
    db: AsyncSession = Depends(get_db),
):
    """Get a single role by ID."""
    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )
    return await _build_role_response(role, db)


@router.put("/{role_id}")
async def update_role(
    role_id: int,
    data: RoleUpdate,
    current_user: User = Depends(require_permission("admin.manage_roles")),
    db: AsyncSession = Depends(get_db),
):
    """Update a role's name, description, or permissions."""
    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )

    # System roles: block permission changes
    if role.is_system and data.permissions is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify permissions of system roles",
        )

    if data.name is not None:
        new_name = data.name.strip()
        new_slug = slugify(new_name)
        if new_slug != role.slug:
            existing = await db.execute(select(Role).where(Role.slug == new_slug))
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A role with slug '{new_slug}' already exists",
                )
            role.slug = new_slug
        role.name = new_name

    if data.permissions is not None:
        role.permissions = data.permissions

    if data.description is not None:
        role.description = data.description

    await db.commit()
    await db.refresh(role)

    logger.info("Role '%s' updated by user %d", role.name, current_user.id)
    return await _build_role_response(role, db)


@router.delete("/{role_id}", status_code=status.HTTP_200_OK)
async def delete_role(
    role_id: int,
    current_user: User = Depends(require_permission("admin.manage_roles")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom role, reassigning users to the system role with the same base_type."""
    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )

    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete system roles",
        )

    # Find the system role with the same base_type for reassignment
    fallback_result = await db.execute(
        select(Role).where(Role.base_type == role.base_type, Role.is_system == True)
    )
    fallback_role = fallback_result.scalar_one_or_none()

    # Reassign users
    users_result = await db.execute(
        select(User).where(User.role_id == role.id)
    )
    users = users_result.scalars().all()
    reassigned_count = len(users)

    for user in users:
        user.role_id = fallback_role.id if fallback_role else None
        user.permission_overrides = {}

    role_name = role.name
    await db.delete(role)
    await db.commit()

    logger.info(
        "Role '%s' deleted by user %d, %d users reassigned",
        role_name, current_user.id, reassigned_count,
    )
    return {
        "message": f"Role '{role_name}' deleted",
        "reassigned_users": reassigned_count,
    }
