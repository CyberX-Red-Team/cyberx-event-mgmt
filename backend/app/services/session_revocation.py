"""End a user's sessions when their login password changes.

Every code path that sets or clears ``users.password_hash`` calls this, so a
password change or reset also locks out anyone holding one of the user's
existing session cookies.

Does not commit: callers run it inside the same transaction as the password
change, so both land together or not at all.
"""
from typing import Iterable, Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session


async def revoke_user_sessions(
    db: AsyncSession,
    user_ids: Iterable[int],
    *,
    keep_token: Optional[str] = None,
) -> int:
    """Deactivate the active sessions of ``user_ids``; return how many.

    ``keep_token`` spares one session -- the caller's own, when a user changes
    their own password and should stay logged in on that device.
    """
    ids = [uid for uid in user_ids if uid is not None]
    if not ids:
        return 0
    stmt = (
        update(Session)
        .where(Session.user_id.in_(ids), Session.is_active.is_(True))
        .values(is_active=False)
        .execution_options(synchronize_session=False)
    )
    if keep_token:
        stmt = stmt.where(Session.session_token != keep_token)
    result = await db.execute(stmt)
    return result.rowcount or 0
