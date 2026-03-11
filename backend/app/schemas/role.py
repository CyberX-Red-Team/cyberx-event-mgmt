"""Pydantic schemas for role management."""
import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator

from app.utils.permissions import ALL_PERMISSIONS


class RoleResponse(BaseModel):
    """Response schema for a role."""
    id: int
    name: str
    slug: str
    base_type: str
    permissions: list[str]
    allowed_role_ids: list[int] = Field(default_factory=list)
    is_system: bool
    description: Optional[str]
    user_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    """Schema for creating a new role."""
    name: str = Field(..., min_length=1, max_length=100)
    base_type: str = Field(..., pattern=r"^(admin|sponsor|invitee)$")
    permissions: list[str] = Field(default_factory=list)
    allowed_role_ids: list[int] = Field(default_factory=list)
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: list[str]) -> list[str]:
        invalid = set(v) - ALL_PERMISSIONS
        if invalid:
            raise ValueError(f"Invalid permissions: {', '.join(sorted(invalid))}")
        return sorted(set(v))


class RoleUpdate(BaseModel):
    """Schema for updating a role."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    permissions: Optional[list[str]] = None
    allowed_role_ids: Optional[list[int]] = None
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        invalid = set(v) - ALL_PERMISSIONS
        if invalid:
            raise ValueError(f"Invalid permissions: {', '.join(sorted(invalid))}")
        return sorted(set(v))


class PermissionOverrideUpdate(BaseModel):
    """Schema for updating a user's permission overrides."""
    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)

    @field_validator("add", "remove")
    @classmethod
    def validate_permissions(cls, v: list[str]) -> list[str]:
        invalid = set(v) - ALL_PERMISSIONS
        if invalid:
            raise ValueError(f"Invalid permissions: {', '.join(sorted(invalid))}")
        return sorted(set(v))


class PermissionGroup(BaseModel):
    """A group of permissions by category."""
    category: str
    permissions: list[str]


class RoleAssignRequest(BaseModel):
    """Schema for assigning a role to a user by role_id."""
    role_id: int


def slugify(name: str) -> str:
    """Generate a URL-friendly slug from a name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
