"""Gate for self-service event access (participants under 18 need guardian consent)."""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import forbidden
from app.dependencies import get_db, require_permission
from app.models.user import User

NOT_CLEARED_MESSAGE = (
    "Your parent or guardian needs to give consent in their portal before you can use this."
)


async def ensure_cleared(db: AsyncSession, user: User) -> None:
    from app.services.event_service import EventService
    from app.services.minor_service import participant_is_cleared
    event = await EventService(db).get_current_event()
    if not await participant_is_cleared(db, user, event):
        raise forbidden(NOT_CLEARED_MESSAGE)


def require_cleared(*perms: str):
    """require_permission(*perms) plus participant_is_cleared for the current event.
    Adults (and anyone without an under-18 record) are always cleared."""
    async def checker(
        current_user: User = Depends(require_permission(*perms)),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_cleared(db, current_user)
        return current_user
    return checker
