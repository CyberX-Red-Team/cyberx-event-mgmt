"""Authentication API routes."""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import (
    get_db,
    get_auth_service,
    get_current_active_user,
    get_session_token
)
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService
from app.models.user import User
from app.models.vpn import VPNCredential
from app.api.utils.validation import normalize_email
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    UserResponse,
    SessionInfo,
    PasswordChangeRequest,
    PasswordChangeResponse,
    PasswordResetRequestSchema,
    PasswordResetRequestResponse,
    PasswordResetCompleteSchema,
    PasswordResetCompleteResponse
)
from app.config import get_settings
from app.api.utils.request import extract_client_metadata
from app.api.utils.response_builders import build_auth_user_response
from app.api.exceptions import not_found, forbidden, bad_request, conflict, unauthorized, server_error, rate_limited


router = APIRouter(prefix="/api/auth", tags=["Authentication"])
settings = get_settings()

import logging
logger = logging.getLogger(__name__)

# Rate limiting storage (in production, use Redis)
# Key: "{prefix}_{ip}", Value: list of attempt timestamps
_rate_limit_cache: dict = {}


def check_rate_limit(
    prefix: str,
    ip_address: str,
    window_minutes: int = 15,
    max_attempts: int = 5
) -> bool:
    """
    Check if IP address has exceeded rate limit for a given action.

    Args:
        prefix: Action prefix (e.g., "login", "reset_request", "reset_complete")
        ip_address: Client IP address
        window_minutes: Time window in minutes
        max_attempts: Maximum attempts allowed

    Returns:
        True if rate limit exceeded, False if OK to proceed
    """
    now = datetime.now(timezone.utc)
    cache_key = f"{prefix}_{ip_address}"

    if cache_key not in _rate_limit_cache:
        _rate_limit_cache[cache_key] = []

    # Clean old entries outside the time window
    window_start = now - timedelta(minutes=window_minutes)
    _rate_limit_cache[cache_key] = [
        ts for ts in _rate_limit_cache[cache_key] if ts > window_start
    ]

    # Check if limit exceeded
    if len(_rate_limit_cache[cache_key]) >= max_attempts:
        return True

    # Record this attempt
    _rate_limit_cache[cache_key].append(now)
    return False


def clear_rate_limit(prefix: str, ip_address: str) -> None:
    """Clear rate limit for an IP address after successful action."""
    cache_key = f"{prefix}_{ip_address}"
    if cache_key in _rate_limit_cache:
        del _rate_limit_cache[cache_key]


def get_rate_limit_count(prefix: str, ip_address: str) -> int:
    """Get current attempt count for an IP within the active window."""
    cache_key = f"{prefix}_{ip_address}"
    return len(_rate_limit_cache.get(cache_key, []))


# Backwards-compatible wrappers for login rate limiting
def check_login_rate_limit(ip_address: str, window_minutes: int = 15, max_attempts: int = 5) -> bool:
    return check_rate_limit("login", ip_address, window_minutes, max_attempts)


def clear_login_rate_limit(ip_address: str) -> None:
    clear_rate_limit("login", ip_address)


async def notify_admins_of_lockout(
    db: AsyncSession,
    lockout_type: str,
    ip_address: str,
    user_agent: str,
    target_email: str | None = None,
    details: str = "",
):
    """
    Send email notification to all active admins about a security lockout.

    Args:
        db: Database session
        lockout_type: Type of lockout (e.g., "password_reset_request", "password_reset_completion")
        ip_address: IP address that triggered the lockout
        user_agent: User-Agent string of the offending client
        target_email: Email address being targeted (if known)
        details: Additional details about the lockout
    """
    # Find all active admin users
    result = await db.execute(
        select(User).where(User.role == "admin", User.is_active == True)
    )
    admins = result.scalars().all()

    if not admins:
        logger.warning(f"Security lockout ({lockout_type}) but no active admins to notify")
        return

    from app.services.email_service import EmailService
    email_service = EmailService(db)

    custom_vars = {
        "lockout_type": lockout_type,
        "ip_address": ip_address,
        "user_agent": user_agent or "Unknown",
        "target_email": target_email or "N/A",
        "details": details,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    for admin in admins:
        try:
            success, message, _ = await email_service.send_email(
                user=admin,
                template_name="admin_security_alert",
                custom_vars={**custom_vars, "admin_name": admin.first_name or "Admin"},
            )
            if not success:
                logger.error(f"Failed to send security alert to {admin.email}: {message}")
        except Exception as e:
            logger.error(f"Failed to send security alert to {admin.email}: {e}")


@router.post("/login", response_model=LoginResponse)
async def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user and create session.

    Rate limited to 5 attempts per 15 minutes per IP address
    to prevent brute force attacks.

    Args:
        login_data: Login credentials
        request: FastAPI request object
        response: FastAPI response object
        auth_service: Auth service instance
        db: Database session

    Returns:
        Login response with user info and session expiry

    Raises:
        HTTPException: If authentication fails or rate limit exceeded
    """
    # Get client info early for rate limiting
    ip_address, user_agent = extract_client_metadata(request)

    # Check rate limit before attempting authentication
    if check_login_rate_limit(ip_address):
        # Log the rate limit violation
        audit_service = AuditService(db)
        await audit_service.log_login(
            user_id=None,
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            details={"reason": "Rate limit exceeded"}
        )
        raise rate_limited(
            "Too many login attempts. Please wait 15 minutes before trying again."
        )

    # Authenticate user
    user = await auth_service.authenticate_user(
        username=login_data.username,
        password=login_data.password
    )

    if not user:
        # Log failed login attempt
        audit_service = AuditService(db)
        await audit_service.log_login(
            user_id=None,
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            details={"username": login_data.username, "reason": "Invalid credentials"}
        )
        raise unauthorized("Incorrect username or password")

    # Clear rate limit on successful authentication
    clear_login_rate_limit(ip_address)

    # Create session
    session_token, expires_at = await auth_service.create_session(
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent
    )

    # Set session cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=not settings.DEBUG,  # HTTPS only in production
        samesite="lax",
        max_age=settings.SESSION_EXPIRY_HOURS * 3600,
        path="/"
    )

    # Log successful login
    audit_service = AuditService(db)
    await audit_service.log_login(
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
        success=True
    )

    # Build user response
    user_response = await build_auth_user_response(user, db)

    return LoginResponse(
        message="Login successful",
        user=user_response,
        expires_at=expires_at
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    session_token: str = Depends(get_session_token),
    auth_service: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Logout user by invalidating session.

    Args:
        request: FastAPI request object
        response: FastAPI response object
        session_token: Session token from cookie
        auth_service: Auth service instance
        db: Database session
        current_user: Current authenticated user

    Returns:
        Logout response
    """
    # Log logout before invalidating session
    ip_address, user_agent = extract_client_metadata(request)

    audit_service = AuditService(db)
    await audit_service.log_logout(
        user_id=current_user.id,
        ip_address=ip_address,
        user_agent=user_agent
    )

    # Invalidate session if token exists
    if session_token:
        await auth_service.invalidate_session(session_token)

    # Clear session cookie
    response.delete_cookie(
        key="session_token",
        path="/"
    )

    return LogoutResponse(message="Logout successful")


@router.get("/me", response_model=SessionInfo)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user),
    session_token: str = Depends(get_session_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current authenticated user information.

    Args:
        current_user: Current authenticated user
        session_token: Session token
        db: Database session

    Returns:
        Current user info with session details
    """
    # Get session expiry
    from app.models.session import Session
    result = await db.execute(
        select(Session).where(Session.session_token == session_token)
    )
    session = result.scalar_one_or_none()

    # Build user response
    user_response = await build_auth_user_response(current_user, db)

    return SessionInfo(
        user=user_response,
        expires_at=session.expires_at if session else None,
        is_admin=current_user.is_admin
    )


@router.post("/password/change", response_model=PasswordChangeResponse)
async def change_password(
    data: PasswordChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Change user's password (requires current password).

    Args:
        data: Password change request with current and new password
        request: FastAPI request object
        current_user: Current authenticated user
        auth_service: Auth service instance
        db: Database session

    Returns:
        Password change response

    Raises:
        HTTPException: If current password is incorrect
    """
    # Verify current password
    user = await auth_service.authenticate_user(
        username=current_user.pandas_username or current_user.email,
        password=data.current_password
    )

    if not user:
        raise unauthorized("Current password is incorrect")

    # Hash new password
    from passlib.context import CryptContext
    from app.api.routes.public import generate_phonetic_password
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    current_user.pandas_password = data.new_password
    current_user.password_hash = pwd_context.hash(data.new_password)
    current_user.password_phonetic = generate_phonetic_password(data.new_password)

    # Queue Keycloak sync for password update (invitees and sponsors only — admins don't have Keycloak accounts)
    if current_user.pandas_username and current_user.role in ('invitee', 'sponsor'):
        from app.services.keycloak_sync_service import KeycloakSyncService
        from app.models.password_sync_queue import SyncOperation
        sync_service = KeycloakSyncService(db)
        await sync_service.queue_user_sync(
            user_id=current_user.id,
            username=current_user.pandas_username,
            password=data.new_password,
            operation=SyncOperation.UPDATE_PASSWORD
        )
        current_user.keycloak_synced = False

    await db.commit()

    # Log password change
    ip_address, user_agent = extract_client_metadata(request)

    audit_service = AuditService(db)
    await audit_service.log_password_change(
        user_id=current_user.id,
        ip_address=ip_address,
        user_agent=user_agent
    )

    return PasswordChangeResponse(
        message="Password changed successfully"
    )


@router.post("/password/reset/request", response_model=PasswordResetRequestResponse)
async def request_password_reset(
    data: PasswordResetRequestSchema,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Request password reset (sends email with reset link).

    Rate limited to 3 requests per 15 minutes per IP to prevent
    email flooding and enumeration timing attacks.

    Args:
        data: Password reset request with email
        request: FastAPI request object
        db: Database session

    Returns:
        Password reset request response

    Note:
        Always returns success to prevent email enumeration
    """
    ip_address, user_agent = extract_client_metadata(request)

    # Rate limit: 3 reset requests per 15 minutes per IP
    if check_rate_limit("reset_request", ip_address, window_minutes=15, max_attempts=3):
        attempts = get_rate_limit_count("reset_request", ip_address)
        logger.warning(
            f"Password reset request rate limit exceeded: IP={ip_address}, "
            f"email={data.email}, attempts={attempts}"
        )

        # Notify admins on lockout
        audit_service = AuditService(db)
        await audit_service.log(
            action="PASSWORD_RESET_REQUEST_RATE_LIMITED",
            user_id=None,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"reason": "Rate limit exceeded", "email": data.email}
        )
        await notify_admins_of_lockout(
            db=db,
            lockout_type="Password Reset Request Flood",
            ip_address=ip_address,
            user_agent=user_agent,
            target_email=data.email,
            details=f"IP exceeded 3 password reset requests in 15 minutes. Targeted email: {data.email}",
        )

        # Still return success to prevent enumeration
        return PasswordResetRequestResponse(
            message="If an account with that email exists, a password reset link has been sent"
        )

    # Find user by email_normalized (case-insensitive and Gmail alias aware)
    normalized_email_value = normalize_email(data.email)
    result = await db.execute(
        select(User).where(User.email_normalized == normalized_email_value)
    )
    user = result.scalar_one_or_none()

    # If user exists, generate reset token and send email
    if user:
        import secrets

        # Invalidate any existing reset token (only latest token works)
        user.password_reset_token = None
        user.password_reset_expires = None

        # Generate secure reset token with 15-minute expiry
        reset_token = secrets.token_urlsafe(32)
        reset_expires = datetime.now(timezone.utc) + timedelta(minutes=15)

        user.password_reset_token = reset_token
        user.password_reset_expires = reset_expires

        await db.commit()

        # Log password reset request
        audit_service = AuditService(db)
        await audit_service.log_password_reset_request(
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent
        )

        # Send password reset email via workflow
        # Delivery mode (immediate vs queued) is controlled by the workflow's
        # send_immediately flag in the DB, configurable from Admin → Workflows.
        from app.services.workflow_service import WorkflowService
        from app.models.email_workflow import WorkflowTriggerEvent

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"

        workflow_service = WorkflowService(db)
        await workflow_service.trigger_workflow(
            trigger_event=WorkflowTriggerEvent.PASSWORD_RESET,
            user_id=user.id,
            custom_vars={
                "reset_url": reset_url,
                "reset_token": reset_token,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "expiry_time": "15 minutes",
            }
        )

    # Always return success to prevent email enumeration
    return PasswordResetRequestResponse(
        message="If an account with that email exists, a password reset link has been sent"
    )


@router.post("/password/reset/complete", response_model=PasswordResetCompleteResponse)
async def complete_password_reset(
    data: PasswordResetCompleteSchema,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Complete password reset using reset token.

    Rate limited to 5 attempts per 15 minutes per IP. After exceeding the
    limit, the IP is locked out and admins are notified.

    Args:
        data: Password reset completion with token and new password
        request: FastAPI request object
        db: Database session

    Returns:
        Password reset completion response

    Raises:
        HTTPException: If token is invalid, expired, or rate limit exceeded
    """
    from passlib.context import CryptContext
    from app.api.routes.public import generate_phonetic_password

    ip_address, user_agent = extract_client_metadata(request)

    # Rate limit: 5 completion attempts per 15 minutes per IP
    if check_rate_limit("reset_complete", ip_address, window_minutes=15, max_attempts=5):
        attempts = get_rate_limit_count("reset_complete", ip_address)
        logger.warning(
            f"Password reset completion rate limit exceeded: IP={ip_address}, attempts={attempts}"
        )

        audit_service = AuditService(db)
        await audit_service.log(
            action="PASSWORD_RESET_COMPLETE_RATE_LIMITED",
            user_id=None,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"reason": "Rate limit exceeded — possible token brute-force"}
        )
        await notify_admins_of_lockout(
            db=db,
            lockout_type="Password Reset Token Brute-Force",
            ip_address=ip_address,
            user_agent=user_agent,
            details=f"IP exceeded 5 password reset completion attempts in 15 minutes. Possible token guessing attack.",
        )

        raise rate_limited(
            "Too many password reset attempts. Please wait 15 minutes before trying again."
        )

    # Find user by reset token
    result = await db.execute(
        select(User).where(User.password_reset_token == data.token)
    )
    user = result.scalar_one_or_none()

    if not user:
        logger.info(f"Invalid reset token attempt from IP={ip_address}")
        raise bad_request("Invalid or expired password reset token")

    # Check if token is expired
    if user.password_reset_expires and user.password_reset_expires < datetime.now(timezone.utc):
        # Clear expired token
        user.password_reset_token = None
        user.password_reset_expires = None
        await db.commit()
        raise bad_request("Password reset token has expired")

    # Token is valid — clear the rate limit for this IP
    clear_rate_limit("reset_complete", ip_address)

    # Hash new password
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    user.pandas_password = data.new_password
    user.password_hash = pwd_context.hash(data.new_password)
    user.password_phonetic = generate_phonetic_password(data.new_password)

    # Clear reset token (single-use)
    user.password_reset_token = None
    user.password_reset_expires = None

    # Queue Keycloak sync for password update (invitees and sponsors only — admins don't have Keycloak accounts)
    if user.pandas_username and user.role in ('invitee', 'sponsor'):
        from app.services.keycloak_sync_service import KeycloakSyncService
        from app.models.password_sync_queue import SyncOperation
        sync_service = KeycloakSyncService(db)
        await sync_service.queue_user_sync(
            user_id=user.id,
            username=user.pandas_username,
            password=data.new_password,
            operation=SyncOperation.UPDATE_PASSWORD
        )
        user.keycloak_synced = False

    await db.commit()

    # Log password reset completion
    audit_service = AuditService(db)
    await audit_service.log_password_reset_complete(
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent
    )

    return PasswordResetCompleteResponse(
        message="Password has been reset successfully"
    )
