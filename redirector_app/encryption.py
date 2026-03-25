"""Minimal Fernet field encryption for the standalone app.

Mirrors app.utils.encryption from cyberx-event-mgmt but is self-contained.
Initialize once at startup with init_encryptor(key).
"""
import os
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

_fernet: Optional[Fernet] = None


def init_encryptor(key: str) -> None:
    global _fernet
    _fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt_field(plaintext: Optional[str]) -> Optional[str]:
    if plaintext is None:
        return None
    if _fernet is None:
        raise RuntimeError("Encryptor not initialized. Call init_encryptor() first.")
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_field(encrypted: Optional[str]) -> Optional[str]:
    if encrypted is None:
        return None
    if _fernet is None:
        raise RuntimeError("Encryptor not initialized. Call init_encryptor() first.")
    try:
        return _fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Decryption failed: invalid token or wrong key.")
