"""Field-level encryption utilities for sensitive data.

Uses Fernet symmetric encryption from the cryptography library to encrypt/decrypt
sensitive fields like passwords that need to be retrievable (unlike bcrypt hashes).

Security Notes:
- Uses AES-128 in CBC mode with HMAC-SHA256 for integrity
- Encryption key must be 32 URL-safe base64-encoded bytes
- Key should be stored securely (environment variable, secrets manager)
- Rotating encryption keys requires re-encrypting all data
"""

from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
import base64
import logging

logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    """Raised when encryption/decryption operations fail."""
    pass


class FieldEncryptor:
    """
    Field-level encryption using Fernet (symmetric encryption).

    Example:
        encryptor = FieldEncryptor(key)
        encrypted = encryptor.encrypt("my secret password")
        decrypted = encryptor.decrypt(encrypted)  # Returns "my secret password"
    """

    def __init__(self, encryption_key: str):
        """
        Initialize encryptor with encryption key.

        Args:
            encryption_key: Base64-encoded Fernet key (32 bytes)

        Raises:
            EncryptionError: If key is invalid
        """
        if not encryption_key:
            raise EncryptionError("Encryption key cannot be empty")

        try:
            # Ensure key is bytes
            if isinstance(encryption_key, str):
                encryption_key = encryption_key.encode('utf-8')

            self.fernet = Fernet(encryption_key)
        except Exception as e:
            raise EncryptionError(f"Invalid encryption key: {e}")

    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """
        Encrypt a plaintext string.

        Args:
            plaintext: String to encrypt (or None)

        Returns:
            Encrypted string (base64-encoded) or None if input is None

        Raises:
            EncryptionError: If encryption fails
        """
        if plaintext is None:
            return None

        if not isinstance(plaintext, str):
            raise EncryptionError(f"Can only encrypt strings, got {type(plaintext)}")

        try:
            # Convert to bytes
            plaintext_bytes = plaintext.encode('utf-8')

            # Encrypt
            encrypted_bytes = self.fernet.encrypt(plaintext_bytes)

            # Return as base64 string (already base64 from Fernet, just decode to str)
            return encrypted_bytes.decode('utf-8')

        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise EncryptionError(f"Failed to encrypt data: {e}")

    def decrypt(self, encrypted: Optional[str]) -> Optional[str]:
        """
        Decrypt an encrypted string.

        Args:
            encrypted: Encrypted string (base64-encoded) or None

        Returns:
            Decrypted plaintext string or None if input is None

        Raises:
            EncryptionError: If decryption fails (wrong key, corrupted data, etc.)
        """
        if encrypted is None:
            return None

        if not isinstance(encrypted, str):
            raise EncryptionError(f"Can only decrypt strings, got {type(encrypted)}")

        try:
            # Convert to bytes
            encrypted_bytes = encrypted.encode('utf-8')

            # Decrypt
            decrypted_bytes = self.fernet.decrypt(encrypted_bytes)

            # Return as string
            return decrypted_bytes.decode('utf-8')

        except InvalidToken:
            logger.error("Decryption failed: Invalid token (wrong key or corrupted data)")
            raise EncryptionError("Failed to decrypt data: Invalid token")

        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise EncryptionError(f"Failed to decrypt data: {e}")

    def is_encrypted(self, value: Optional[str]) -> bool:
        """
        Check if a value appears to be encrypted.

        This is a heuristic check - tries to decrypt and returns True if successful.
        Not 100% reliable but useful for migration.

        Args:
            value: String to check

        Returns:
            True if value appears encrypted, False otherwise
        """
        if not value:
            return False

        try:
            self.decrypt(value)
            return True
        except EncryptionError:
            return False


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.

    Returns:
        Base64-encoded encryption key suitable for use with FieldEncryptor

    Example:
        key = generate_encryption_key()
        # Save to .env file:
        # ENCRYPTION_KEY=<key>
    """
    key = Fernet.generate_key()
    return key.decode('utf-8')


# Singleton instance for global use
_encryptor: Optional[FieldEncryptor] = None


def get_encryptor() -> FieldEncryptor:
    """
    Get the global FieldEncryptor instance.

    Returns:
        Configured FieldEncryptor instance

    Raises:
        EncryptionError: If encryptor not initialized (call init_encryptor first)
    """
    global _encryptor
    if _encryptor is None:
        raise EncryptionError(
            "Encryptor not initialized. Call init_encryptor() first."
        )
    return _encryptor


def init_encryptor(encryption_key: str) -> None:
    """
    Initialize the global FieldEncryptor instance.

    Should be called once at application startup.

    Args:
        encryption_key: Base64-encoded Fernet key

    Raises:
        EncryptionError: If key is invalid
    """
    global _encryptor
    _encryptor = FieldEncryptor(encryption_key)
    logger.info("Field encryptor initialized successfully")


# Convenience functions that use the global encryptor
def encrypt_field(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a field using the global encryptor."""
    return get_encryptor().encrypt(plaintext)


def decrypt_field(encrypted: Optional[str]) -> Optional[str]:
    """Decrypt a field using the global encryptor."""
    return get_encryptor().decrypt(encrypted)


def is_field_encrypted(value: Optional[str]) -> bool:
    """Check if a field appears to be encrypted."""
    return get_encryptor().is_encrypted(value)
