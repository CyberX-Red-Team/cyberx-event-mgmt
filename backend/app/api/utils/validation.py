"""Validation utilities."""
from typing import List
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User


async def validate_bulk_email_permissions(
    users: List[User],
    db: AsyncSession,
    email_type: str = "bulk emails"
) -> None:
    """
    Validate bulk email operation permissions and safeguards.

    Checks:
    - Active event exists
    - Test mode restrictions (sponsors only)
    - Registration open status (for non-test mode)

    Args:
        users: List of User objects to send emails to
        db: Database session
        email_type: Type of email for error messages (default "bulk emails")

    Raises:
        HTTPException: If validation fails (403 Forbidden)
    """
    # Only enforce these checks for bulk operations (10+ users)
    if len(users) < 10:
        return

    from app.models.event import Event

    result = await db.execute(
        select(Event).where(Event.is_active == True).order_by(Event.year.desc())
    )
    active_event = result.scalar_one_or_none()

    if not active_event:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No active event found. Cannot send {email_type}."
        )

    # Check if all recipients are sponsors
    all_sponsors = all(user.is_sponsor_role for user in users)

    # TEST MODE ALWAYS RESTRICTS: If test mode is enabled, only sponsors can receive emails
    if active_event.test_mode:
        if not all_sponsors:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot send {email_type} to non-sponsors while {active_event.name} is in test mode. "
                       f"Test mode restricts all emails to sponsors only. "
                       f"Disable test mode or send only to sponsor users."
            )
    # NOT IN TEST MODE: Require registration to be open for bulk emails
    elif not active_event.registration_open:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot send {email_type} to {len(users)} users. "
                   f"Registration is not open for {active_event.name}. "
                   f"Enable 'Registration Open' in event settings to send bulk emails."
        )
