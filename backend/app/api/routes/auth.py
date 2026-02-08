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

# Rate limiting storage (in production, use Redis)
# Key: IP address, Value: list of login attempt timestamps
_login_rate_limit_cache: dict = {}


def check_login_rate_limit(
    ip_address: str,
    window_minutes: int = 15,
    max_attempts: int = 5
) -> bool:
    """
    Check if IP address has exceeded login rate limit.

    Args:
        ip_address: Client IP address
        window_minutes: Time window in minutes (default 15)
        max_attempts: Maximum login attempts allowed (default 5)

    Returns:
        True if rate limit exceeded, False if OK to proceed
    """
    now = datetime.now(timezone.utc)
    cache_key = f"login_{ip_address}"

    if cache_key not in _login_rate_limit_cache:
        _login_rate_limit_cache[cache_key] = []

    # Clean old entries outside the time window
    window_start = now - timedelta(minutes=window_minutes)
    _login_rate_limit_cache[cache_key] = [
        ts for ts in _login_rate_limit_cache[cache_key] if ts > window_start
    ]

    # Check if limit exceeded
    if len(_login_rate_limit_cache[cache_key]) >= max_attempts:
        return True

    # Record this attempt
    _login_rate_limit_cache[cache_key].append(now)
    return False


def clear_login_rate_limit(ip_address: str) -> None:
    """
    Clear login rate limit for an IP address after successful login.

    Args:
        ip_address: Client IP address
    """
    cache_key = f"login_{ip_address}"
    if cache_key in _login_rate_limit_cache:
        del _login_rate_limit_cache[cache_key]


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

    Args:
        data: Password reset request with email
        request: FastAPI request object
        db: Database session

    Returns:
        Password reset request response

    Note:
        Always returns success to prevent email enumeration
    """
    # Find user by email_normalized (case-insensitive and Gmail alias aware)
    normalized_email_value = normalize_email(data.email)
    result = await db.execute(
        select(User).where(User.email_normalized == normalized_email_value)
    )
    user = result.scalar_one_or_none()

    # If user exists, generate reset token and send email
    if user:
        import secrets
        from datetime import datetime, timezone, timedelta

        # Generate secure reset token
        reset_token = secrets.token_urlsafe(32)
        reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)

        user.password_reset_token = reset_token
        user.password_reset_expires = reset_expires

        await db.commit()

        # Log password reset request
        ip_address, user_agent = extract_client_metadata(request)

        audit_service = AuditService(db)
        await audit_service.log_password_reset_request(
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent
        )

        # Send password reset email via workflow
        from app.services.workflow_service import WorkflowService
        from app.models.email_workflow import WorkflowTriggerEvent
        from app.config import get_settings

        settings = get_settings()
        workflow_service = WorkflowService(db)

        # Build password reset URL using configured frontend URL
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"

        await workflow_service.trigger_workflow(
            trigger_event=WorkflowTriggerEvent.PASSWORD_RESET,
            user_id=user.id,
            custom_vars={
                "reset_url": reset_url,
                "reset_token": reset_token,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email
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

    Args:
        data: Password reset completion with token and new password
        request: FastAPI request object
        db: Database session

    Returns:
        Password reset completion response

    Raises:
        HTTPException: If token is invalid or expired
    """
    from datetime import datetime, timezone
    from passlib.context import CryptContext
    from app.api.routes.public import generate_phonetic_password

    # Find user by reset token
    result = await db.execute(
        select(User).where(User.password_reset_token == data.token)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise bad_request("Invalid or expired password reset token")

    # Check if token is expired
    if user.password_reset_expires and user.password_reset_expires < datetime.now(timezone.utc):
        raise bad_request("Password reset token has expired")

    # Hash new password
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    user.pandas_password = data.new_password
    user.password_hash = pwd_context.hash(data.new_password)
    user.password_phonetic = generate_phonetic_password(data.new_password)

    # Clear reset token
    user.password_reset_token = None
    user.password_reset_expires = None

    await db.commit()

    # Log password reset completion
    ip_address, user_agent = extract_client_metadata(request)

    audit_service = AuditService(db)
    await audit_service.log_password_reset_complete(
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent
    )

    return PasswordResetCompleteResponse(
        message="Password has been reset successfully"
    )
