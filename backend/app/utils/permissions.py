"""Permission constants and resolution utilities for the roles & permissions system."""
from typing import Set


# All permission strings defined in the system (44 total)
ALL_PERMISSIONS: Set[str] = {
    # Events (4)
    "events.view",
    "events.create",
    "events.edit",
    "events.delete",

    # Participants (6)
    "participants.view",
    "participants.view_all",
    "participants.create",
    "participants.edit",
    "participants.remove",
    "participants.invite",

    # Instances (6)
    "instances.view",
    "instances.view_all",
    "instances.provision",
    "instances.delete",
    "instances.manage_agent",
    "instances.sync_status",

    # VPN (4)
    "vpn.view",
    "vpn.request",
    "vpn.download",
    "vpn.manage_pool",

    # Email (6)
    "email.view",
    "email.send",
    "email.send_bulk",
    "email.manage_templates",
    "email.manage_queue",
    "email.manage_workflows",

    # TLS Certificates (3)
    "tls.request",
    "tls.download",
    "tls.manage",

    # CPE Certificates (2)
    "cpe.download",
    "cpe.manage",

    # Cloud Infrastructure (3)
    "cloud.manage_providers",
    "cloud.manage_templates",
    "cloud.manage_images",

    # Licenses (2)
    "licenses.view",
    "licenses.manage",

    # Participant Actions (2)
    "actions.view",
    "actions.manage",

    # Keycloak (1)
    "keycloak.manage",

    # Admin / System (5)
    "admin.manage_users",
    "admin.manage_roles",
    "admin.view_audit_log",
    "admin.manage_settings",
    "scheduler.view",
}


# Default permission sets for built-in roles
ROLE_PERMISSIONS: dict[str, Set[str]] = {
    "admin": ALL_PERMISSIONS.copy(),

    "sponsor": {
        # Invitee self-service permissions (11)
        "instances.view",
        "instances.provision",
        "instances.delete",
        "instances.manage_agent",
        "vpn.view",
        "vpn.request",
        "vpn.download",
        "tls.request",
        "tls.download",
        "cpe.download",
        # Sponsor management permissions (4)
        "participants.view",
        "participants.create",
        "participants.edit",
        "participants.invite",
    },

    "invitee": {
        "instances.view",
        "instances.provision",
        "instances.delete",
        "instances.manage_agent",
        "vpn.view",
        "vpn.request",
        "vpn.download",
        "tls.request",
        "tls.download",
        "cpe.download",
    },
}


def get_permissions_for_role_string(role: str) -> Set[str]:
    """
    Get default permissions for a legacy role string.

    Used as fallback when user.role_obj is None but user.role is set.

    Args:
        role: Role string ("admin", "sponsor", "invitee")

    Returns:
        Set of permission strings (empty set for unknown roles)
    """
    return ROLE_PERMISSIONS.get(role.lower(), set()).copy()


def resolve_permissions(
    base: Set[str],
    add: Set[str] | None = None,
    remove: Set[str] | None = None,
) -> Set[str]:
    """
    Resolve effective permissions from base set + overrides.

    effective = (base | add) - remove

    Args:
        base: Base permission set (from role)
        add: Permissions to add (user overrides)
        remove: Permissions to remove (user overrides)

    Returns:
        Effective permission set
    """
    result = base.copy()
    if add:
        result |= add
    if remove:
        result -= remove
    return result
