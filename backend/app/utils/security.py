"""Security utilities for password hashing and token generation."""
import secrets
from passlib.context import CryptContext

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def generate_secure_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(nbytes)


def generate_session_token() -> str:
    """Generate a session token (32 bytes)."""
    return generate_secure_token(32)


def generate_reset_token() -> str:
    """Generate a password reset token (32 bytes)."""
    return generate_secure_token(32)
