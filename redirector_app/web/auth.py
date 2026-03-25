"""Session-based authentication for the standalone web UI.

Provides bcrypt password verification and HS256 JWT sessions stored in
HTTP-only cookies. This mirrors the cyberx-event-mgmt auth pattern but uses
a single admin credential from environment variables instead of a database
user table — keeping standalone deployment simple and self-contained.

Environment variables:
    ADMIN_USERNAME          Admin login username (default: "admin")
    ADMIN_PASSWORD_HASH     bcrypt hash of the admin password (REQUIRED for web UI)
    ADMIN_EMAIL             Email shown in sidebar footer (default: "admin@localhost")
    SECRET_KEY              HS256 JWT signing secret (REQUIRED)
    SESSION_EXPIRY_MINUTES  JWT lifetime in minutes (default: 480 = 8 hours)
    APP_ENV                 Set to "production" to enable Secure cookie flag
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt


# ---------------------------------------------------------------------------
# Admin credential dataclass
# ---------------------------------------------------------------------------

@dataclass
class WebAdminUser:
    """Minimal user object passed to Jinja2 templates for the web UI."""
    username: str
    email: str
    first_name: str
    last_name: str = ""

    @property
    def display_name(self) -> str:
        return self.first_name or self.username


# ---------------------------------------------------------------------------
# Password verification
# ---------------------------------------------------------------------------

def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain-text password matches the bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def get_admin_credentials() -> tuple[str, str]:
    """Return (username, password_hash) from environment. Raises RuntimeError if unset."""
    username = os.environ.get("ADMIN_USERNAME", "admin").strip()
    password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
    if not password_hash:
        raise RuntimeError(
            "ADMIN_PASSWORD_HASH environment variable is not set. "
            "Generate one with: python -c \"import bcrypt; "
            "print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt(12)).decode())\""
        )
    return username, password_hash


# ---------------------------------------------------------------------------
# JWT session tokens
# ---------------------------------------------------------------------------

_ALGORITHM = "HS256"


def _secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "").strip()
    if not key:
        raise RuntimeError("SECRET_KEY environment variable is not set.")
    return key


def _session_expiry_minutes() -> int:
    try:
        return int(os.environ.get("SESSION_EXPIRY_MINUTES", "480"))
    except (ValueError, TypeError):
        return 480


def create_session_token(username: str) -> str:
    """Create a signed HS256 JWT for the given admin username."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=_session_expiry_minutes())
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _secret_key(), algorithm=_ALGORITHM)


def decode_session_token(token: str) -> Optional[str]:
    """
    Decode and validate a session JWT.

    Returns the username (sub claim) on success, or None if the token is
    missing, expired, tampered with, or otherwise invalid.
    """
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[_ALGORITHM])
        username: Optional[str] = payload.get("sub")
        return username if username else None
    except JWTError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers for building the WebAdminUser from env
# ---------------------------------------------------------------------------

def build_web_admin_user(username: str) -> WebAdminUser:
    """Build a WebAdminUser dataclass from env vars for template context."""
    email = os.environ.get("ADMIN_EMAIL", "admin@localhost").strip()
    return WebAdminUser(
        username=username,
        email=email,
        first_name=username.capitalize(),
    )
