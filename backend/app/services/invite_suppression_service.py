"""Do-not-invite list: only for people who asked not to be invited again."""
from __future__ import annotations

import hashlib
import hmac

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils.validation import normalize_email
from app.config import get_settings
from app.models.invite_suppression import InviteSuppression

# Shown to whoever tries to add a suppressed person. Deliberately says nothing else.
SUPPRESSED_MESSAGE = "This person asked not to be invited again."


class InvitationSuppressed(Exception):
    """Raised when an invitation would go to someone on the do-not-invite list."""

    def __init__(self):
        super().__init__(SUPPRESSED_MESSAGE)


def _key() -> bytes:
    settings = get_settings()
    if settings.INVITE_SUPPRESSION_KEY:
        return settings.INVITE_SUPPRESSION_KEY.encode()
    # Derive a purpose-specific key so the raw SECRET_KEY is never the HMAC key.
    return hmac.new(
        settings.SECRET_KEY.encode(), b"cyberx-invite-suppression-v1", hashlib.sha256
    ).digest()


_GMAIL_ALIASES = {"googlemail.com": "gmail.com"}


def suppression_key(email: str) -> str:
    """
    The form of an address the do-not-invite list matches on. Stricter than
    account normalization (normalize_email): it also drops any +tag and treats
    googlemail.com as gmail.com, because those all deliver to the same inbox.
    Erring towards blocking is fine here: only the inbox that asked is affected.
    """
    normalized = normalize_email(email or "")
    if "@" not in normalized:
        return normalized
    local, domain = normalized.rsplit("@", 1)
    local = local.split("+", 1)[0]
    domain = _GMAIL_ALIASES.get(domain, domain)
    return f"{local}@{domain}"


def email_hmac(email: str) -> str:
    """HMAC-SHA256 hex of suppression_key(email): stable across case, whitespace,
    Gmail dots, +tags and googlemail.com."""
    return hmac.new(_key(), suppression_key(email).encode(), hashlib.sha256).hexdigest()


class InviteSuppressionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_suppressed(self, email: str) -> bool:
        result = await self.session.execute(
            select(InviteSuppression.email_hmac).where(
                InviteSuppression.email_hmac == email_hmac(email)
            )
        )
        return result.scalar_one_or_none() is not None

    async def add(self, email: str) -> bool:
        """Add an entry (no commit). Returns False if it already existed."""
        if await self.is_suppressed(email):
            return False
        self.session.add(InviteSuppression(email_hmac=email_hmac(email)))
        return True

    async def remove(self, email: str) -> bool:
        """Remove an entry (no commit). Returns False if there wasn't one."""
        result = await self.session.execute(
            delete(InviteSuppression).where(InviteSuppression.email_hmac == email_hmac(email))
        )
        return (result.rowcount or 0) > 0
