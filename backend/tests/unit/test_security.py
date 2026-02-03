"""
Unit tests for security utilities.

Tests password hashing, token generation, and security functions.
"""

import pytest
from app.utils.security import (
    hash_password,
    verify_password,
    generate_secure_token,
    generate_session_token,
    generate_reset_token,
)


@pytest.mark.unit
@pytest.mark.security
class TestPasswordHashing:
    """Test password hashing functions."""

    def test_hash_password(self):
        """Test password hashing produces a hash."""
        password = "test_password123"
        hashed = hash_password(password)

        assert hashed != password
        assert len(hashed) > 50  # bcrypt hashes are long
        assert hashed.startswith("$2b$")  # bcrypt prefix

    def test_verify_password_correct(self):
        """Test password verification with correct password."""
        password = "test_password123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test password verification with incorrect password."""
        password = "test_password123"
        wrong_password = "wrong_password"
        hashed = hash_password(password)

        assert verify_password(wrong_password, hashed) is False

    def test_hash_password_same_password_different_hash(self):
        """Test that hashing same password twice produces different hashes."""
        password = "test_password123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Bcrypt includes salt, so hashes should differ
        assert hash1 != hash2

        # But both should verify correctly
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True

    def test_hash_password_special_characters(self):
        """Test hashing password with special characters."""
        password = "P@ssw0rd!@#$%^&*()"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_hash_password_unicode(self):
        """Test hashing password with unicode characters."""
        password = "密码Pāsswörd™"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_empty(self):
        """Test password verification with empty strings."""
        password = "test_password"
        hashed = hash_password(password)

        assert verify_password("", hashed) is False


@pytest.mark.unit
@pytest.mark.security
class TestTokenGeneration:
    """Test token generation functions."""

    def test_generate_secure_token(self):
        """Test secure token generation."""
        token = generate_secure_token(32)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 40  # URL-safe base64 encoding makes it longer

    def test_generate_secure_token_different_each_time(self):
        """Test that token generation produces unique tokens."""
        token1 = generate_secure_token(32)
        token2 = generate_secure_token(32)

        assert token1 != token2

    def test_generate_session_token(self):
        """Test session token generation."""
        token = generate_session_token()

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 40

    def test_generate_reset_token(self):
        """Test password reset token generation."""
        token = generate_reset_token()

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 40

    def test_tokens_are_url_safe(self):
        """Test that generated tokens are URL-safe."""
        token = generate_secure_token(32)

        # URL-safe means no special characters that need encoding
        import string
        url_safe_chars = string.ascii_letters + string.digits + "-_"
        assert all(c in url_safe_chars for c in token)
