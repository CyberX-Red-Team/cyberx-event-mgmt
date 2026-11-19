"""Redact secrets from JSON-like data before it is stored at rest.

Used for audit log details (on write) and for email queue template variables
(once an email is finished), so passwords, private keys and reset tokens are
not kept in plaintext outside their encrypted columns.

Matching is by exact key name, case-insensitive. Deliberately NOT by
substring: keys such as ``tokens_used``, ``token_hash`` and ``ssh_public_key``
are not secrets and must survive.
"""
from typing import Any

REDACTED = "[REDACTED]"

SECRET_KEYS = frozenset({
    # Passwords (portal / pandas credentials and their phonetic spelling)
    "password",
    "pandas_password",
    "password_phonetic",
    "new_password",
    "old_password",
    "current_password",
    "confirm_password",
    # Keys
    "ssh_private_key",
    "private_key",
    "api_key",
    "secret",
    "client_secret",
    "totp_secret",
    # Tokens (reset_url embeds the reset token)
    "reset_token",
    "reset_url",
    "session_token",
})


def is_secret_key(key: Any) -> bool:
    return isinstance(key, str) and key.lower() in SECRET_KEYS


def _mask(value: Any) -> Any:
    """Replace every non-null leaf with REDACTED, keeping the shape.

    Keeping the shape preserves useful structure: an EVENT_UPDATE change entry
    still shows that an old/new value existed (or was null) without the value.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask(v) for v in value]
    return REDACTED


def redact_secrets(value: Any) -> Any:
    """Return a copy of ``value`` with values under secret keys masked.

    Never mutates the input: callers (e.g. the event update route) keep using
    their own dict after it has been logged.
    """
    if isinstance(value, dict):
        return {
            k: _mask(v) if is_secret_key(k) else redact_secrets(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_secrets(v) for v in value]
    return value
