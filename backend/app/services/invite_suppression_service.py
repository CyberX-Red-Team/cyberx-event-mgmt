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


def _key() -> bytes:
    settings = get_settings()
    if settings.INVITE_SUPPRESSION_KEY:
        return settings.INVITE_SUPPRESSION_KEY.encode()
    # Derive a purpose-specific key so the raw SECRET_KEY is never the HMAC key.
    return hmac.new(
        settings.SECRET_KEY.encode(), b"cyberx-invite-suppression-v1", hashlib.sha256
    ).digest()


def email_hmac(email: str) -> str:
    """HMAC-SHA256 hex of the normalized email (stable across case/whitespace/Gmail dots)."""
    return hmac.new(_key(), normalize_email(email).encode(), hashlib.sha256).hexdigest()


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
