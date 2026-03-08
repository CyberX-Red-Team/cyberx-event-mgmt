"""FastAPI dependencies for authentication and authorization."""
import hashlib
import logging
from typing import Optional
from fastapi import Cookie, Depends, HTTPException, status, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.instance import Instance
from app.services.auth_service import AuthService
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def get_db() -> AsyncSession:
    """
    Dependency to get database session.

    Yields:
        Database session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_auth_service(
    db: AsyncSession = Depends(get_db)
) -> AuthService:
    """
    Dependency to get auth service.

    Args:
        db: Database session

    Returns:
        AuthService instance
    """
    return AuthService(
        session=db,
        session_expiry_hours=settings.SESSION_EXPIRY_HOURS
    )


async def get_session_token(
    session_token: Optional[str] = Cookie(None, alias="session_token")
) -> Optional[str]:
    """
    Extract session token from cookie.

    Args:
        session_token: Session token from cookie

    Returns:
        Session token or None
    """
    return session_token


async def get_current_user(
    session_token: Optional[str] = Depends(get_session_token),
    auth_service: AuthService = Depends(get_auth_service)
) -> User:
    """
    Get the current authenticated user.

    Args:
        session_token: Session token from cookie
        auth_service: Auth service instance

    Returns:
        Current user

    Raises:
        HTTPException: If not authenticated or session invalid
    """
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Cookie"},
        )

    user = await auth_service.validate_session(session_token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Cookie"},
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get the current active user.

    Args:
        current_user: Current user from get_current_user

    Returns:
        Current active user

    Raises:
        HTTPException: If user is not active
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """
    Get the current admin user.

    Admins have full access to:
    - All participant management
    - Bulk email communications
    - VPN credential management
    - System configuration

    Args:
        current_user: Current active user

    Returns:
        Current admin user

    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_admin_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized. Admin access required."
        )
    return current_user


async def get_current_sponsor_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """
    Get the current sponsor user (or admin).

    Sponsors can:
    - Manage participants they sponsor
    - View their sponsored participants
    - Send emails to their sponsored participants

    Admins automatically have sponsor privileges.

    Args:
        current_user: Current active user

    Returns:
        Current sponsor user

    Raises:
        HTTPException: If user is not a sponsor or admin
    """
    if not current_user.is_sponsor_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized. Sponsor access required."
        )
    return current_user


async def get_optional_user(
    session_token: Optional[str] = Depends(get_session_token),
    auth_service: AuthService = Depends(get_auth_service)
) -> Optional[User]:
    """
    Get the current user if authenticated, otherwise None.

    Useful for pages that work for both authenticated and unauthenticated users.

    Args:
        session_token: Session token from cookie
        auth_service: Auth service instance

    Returns:
        User object if authenticated, None otherwise
    """
    if not session_token:
        return None

    user = await auth_service.validate_session(session_token)
    return user


def require_role(*roles: UserRole):
    """
    Factory function to create a dependency that requires specific roles.

    Used by views.py for base_type-level checks (sidebar, redirects).

    Args:
        *roles: One or more UserRole values that are allowed

    Returns:
        Dependency function
    """
    async def role_checker(
        current_user: User = Depends(get_current_active_user)
    ) -> User:
        role_values = [r.value for r in roles]
        if current_user.role not in role_values and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not authorized. Required role: {', '.join(role_values)}"
            )
        return current_user
    return role_checker


def require_permission(*perms: str):
    """
    Factory function to create a dependency that requires specific permissions.

    Checks the user's effective permissions (role permissions + overrides).

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: User = Depends(require_permission("events.view"))):
            ...

    Args:
        *perms: One or more permission strings that are ALL required

    Returns:
        Dependency function
    """
    async def permission_checker(
        current_user: User = Depends(get_current_active_user)
    ) -> User:
        if not current_user.has_permission(*perms):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permissions: {', '.join(perms)}"
            )
        return current_user
    return permission_checker


class PermissionChecker:
    """
    Permission checker for fine-grained access control on specific resources.

    Used for participant/VPN scoping where the check depends on the
    relationship between the user and the target resource.
    """

    def can_view_participant(self, user: User, participant: User) -> None:
        """Check if user can view a participant."""
        # Users can always view themselves
        if user.id == participant.id:
            return
        # Users with participants.view_all can view anyone
        if user.has_permission("participants.view_all"):
            return
        # Users with participants.view can view their sponsored participants
        if user.has_permission("participants.view"):
            if participant.sponsor_id == user.id:
                return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this participant"
        )

    def can_edit_participant(self, user: User, participant: User) -> None:
        """Check if user can edit a participant."""
        # Users cannot edit themselves (except via profile endpoint)
        if user.id == participant.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Use the profile endpoint to edit your own account"
            )
        if not user.has_permission("participants.edit"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to edit this participant"
            )
        # Users with participants.view_all can edit anyone
        if user.has_permission("participants.view_all"):
            return
        # Sponsors can only edit their sponsored participants
        if participant.sponsor_id == user.id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to edit this participant"
        )

    def can_delete_participant(self, user: User, participant: User) -> None:
        """Check if user can delete a participant."""
        if not user.has_permission("participants.remove"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete participants"
            )
        # Cannot delete yourself
        if user.id == participant.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete your own account"
            )

    def can_send_bulk_email(self, user: User) -> None:
        """Check if user can send bulk emails to all participants."""
        if not user.has_permission("email.send_bulk"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to send bulk emails"
            )

    def can_manage_vpn(self, user: User) -> None:
        """Check if user can manage VPN credentials."""
        if not user.has_permission("vpn.manage_pool"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to manage VPN credentials"
            )

    def can_assign_vpn_to_participant(self, user: User, participant: User) -> None:
        """Check if user can assign VPN to a specific participant."""
        if not user.has_permission("vpn.manage_pool"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to assign VPN credentials"
            )
        # Users with participants.view_all can assign to anyone
        if user.has_permission("participants.view_all"):
            return
        # Sponsors can assign to their sponsored participants
        if participant.sponsor_id == user.id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to assign VPN to this participant"
        )


# Global permission checker instance
permissions = PermissionChecker()


def _extract_client_ip(request: Request) -> str:
    """Extract client IP, respecting proxy headers when configured."""
    if settings.AGENT_TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    return request.client.host if request.client else "unknown"


async def get_current_agent_instance(
    request: Request,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Instance:
    """Authenticate an instance agent via Bearer token + IP binding.

    1. Extract Bearer token, SHA-256 hash it, look up instance
    2. Verify instance is not soft-deleted
    3. First connection: record source IP as agent_registered_ip
    4. Subsequent connections: verify source IP matches
    """
    # Extract Bearer token
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
        )
    raw_token = parts[1]

    # Hash and look up
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    result = await db.execute(
        select(Instance).where(
            Instance.agent_token_hash == token_hash,
            Instance.deleted_at.is_(None),
        )
    )
    instance = result.scalar_one_or_none()

    if not instance:
        logger.warning(
            "Agent auth failed: invalid token from %s",
            _extract_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid agent token",
        )

    # IP binding
    client_ip = _extract_client_ip(request)

    if instance.agent_registered_ip is None:
        # First connection — record IP
        instance.agent_registered_ip = client_ip
        await db.commit()
        logger.info(
            "Agent for instance %d registered IP: %s",
            instance.id, client_ip,
        )
    elif instance.agent_registered_ip != client_ip:
        logger.warning(
            "Agent IP mismatch for instance %d: "
            "registered=%s, actual=%s",
            instance.id, instance.agent_registered_ip, client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent IP does not match registered IP",
        )

    return instance
