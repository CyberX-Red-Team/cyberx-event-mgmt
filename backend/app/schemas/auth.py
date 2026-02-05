"""Pydantic schemas for authentication."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Login request schema."""

    username: str = Field(..., description="Email or pandas username")
    password: str = Field(..., min_length=1, description="Password")


class LoginResponse(BaseModel):
    """Login response schema."""

    message: str
    user: "UserResponse"
    expires_at: datetime


class LogoutResponse(BaseModel):
    """Logout response schema."""

    message: str


class UserResponse(BaseModel):
    """User response schema (for /me endpoint)."""

    id: int
    email: EmailStr
    first_name: str
    last_name: str
    country: str
    is_admin: bool
    is_active: bool
    confirmed: str
    email_status: str
    theme_preference: str

    # Optional fields
    pandas_username: Optional[str] = None
    discord_username: Optional[str] = None
    snowflake_id: Optional[str] = None

    # VPN status
    has_vpn: bool = False

    model_config = {
        "from_attributes": True
    }


class SessionInfo(BaseModel):
    """Session information schema."""

    user: UserResponse
    expires_at: datetime
    is_admin: bool


class PasswordChangeRequest(BaseModel):
    """Password change request schema."""

    current_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(..., min_length=8, description="New password (minimum 8 characters)")


class PasswordChangeResponse(BaseModel):
    """Password change response schema."""

    message: str
    success: bool = True


class PasswordResetRequestSchema(BaseModel):
    """Password reset request schema."""

    email: EmailStr = Field(..., description="Email address")


class PasswordResetRequestResponse(BaseModel):
    """Password reset request response schema."""

    message: str
    success: bool = True


class PasswordResetCompleteSchema(BaseModel):
    """Password reset completion schema."""

    token: str = Field(..., description="Password reset token")
    new_password: str = Field(..., min_length=8, description="New password (minimum 8 characters)")


class PasswordResetCompleteResponse(BaseModel):
    """Password reset completion response schema."""

    message: str
    success: bool = True
