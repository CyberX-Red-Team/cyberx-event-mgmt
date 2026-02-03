"""FastAPI dependencies for authentication and authorization."""
from typing import Optional
from fastapi import Cookie, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.services.auth_service import AuthService
from app.config import get_settings


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

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: User = Depends(require_role(UserRole.ADMIN))):
            ...

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


class PermissionChecker:
    """
    Permission checker for fine-grained access control.

    Usage:
        permission_checker = PermissionChecker()

        @router.get("/participants/{participant_id}")
        async def get_participant(
            participant_id: int,
            current_user: User = Depends(get_current_active_user),
            db: AsyncSession = Depends(get_db)
        ):
            participant = await get_participant_by_id(db, participant_id)
            permission_checker.can_view_participant(current_user, participant)
            return participant
    """

    def can_view_participant(self, user: User, participant: User) -> None:
        """Check if user can view a participant."""
        # Users can always view themselves
        if user.id == participant.id:
            return
        # Admins and sponsors can view anyone
        if user.is_sponsor_role:  # This includes admins (is_sponsor_role includes admin role)
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
        # Admins can edit anyone
        if user.is_admin_role:
            return
        # Sponsors can edit their sponsored participants
        if user.is_sponsor_role and participant.sponsor_id == user.id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to edit this participant"
        )

    def can_delete_participant(self, user: User, participant: User) -> None:
        """Check if user can delete a participant."""
        # Only admins can delete participants
        if not user.is_admin_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can delete participants"
            )
        # Cannot delete yourself
        if user.id == participant.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete your own account"
            )

    def can_send_bulk_email(self, user: User) -> None:
        """Check if user can send bulk emails to all participants."""
        if not user.can_send_bulk_emails:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can send bulk emails to all participants"
            )

    def can_manage_vpn(self, user: User) -> None:
        """Check if user can manage VPN credentials."""
        if not user.is_admin_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can manage VPN credentials"
            )

    def can_assign_vpn_to_participant(self, user: User, participant: User) -> None:
        """Check if user can assign VPN to a specific participant."""
        # Admins can assign to anyone
        if user.is_admin_role:
            return
        # Sponsors can assign to their sponsored participants
        if user.is_sponsor_role and participant.sponsor_id == user.id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to assign VPN to this participant"
        )


# Global permission checker instance
permissions = PermissionChecker()
