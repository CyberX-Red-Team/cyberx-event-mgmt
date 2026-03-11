"""Validation utilities."""
from typing import List
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User


def normalize_email(email: str) -> str:
    """
    Normalize email address for consistent storage and comparison.

    - Converts to lowercase for case-insensitive comparison
    - Strips leading/trailing whitespace
    - Gmail/Google Workspace specific normalization:
      - Removes periods (.) from local part (before @)
      - PRESERVES plus addressing (+tag) for email delivery and filtering
    - Ensures consistent format across the application

    Args:
        email: Email address to normalize

    Returns:
        Normalized email address (lowercase, trimmed, Gmail periods removed)

    Examples:
        >>> normalize_email("  John.Doe@EXAMPLE.COM  ")
        "john.doe@example.com"
        >>> normalize_email("Wes.Huang@Gmail.com")
        "weshuang@gmail.com"
        >>> normalize_email("wes+work@gmail.com")
        "wes+work@gmail.com"  # + addressing preserved
        >>> normalize_email("test.user@company.com")
        "test.user@company.com"

    Note:
        Plus addressing (+tag) is intentionally preserved so users can:
        - Receive emails at their preferred alias
        - Use email filters based on + tags
        - Maintain their intended email configuration
    """
    if not email:
        return email

    # Strip whitespace and convert to lowercase
    email = email.strip().lower()

    # Split into local part and domain
    if '@' not in email:
        return email

    local_part, domain = email.rsplit('@', 1)

    # Gmail and Google Workspace specific normalization
    # Gmail ignores periods in email addresses
    gmail_domains = {'gmail.com', 'googlemail.com'}
    if domain in gmail_domains or domain.endswith('.google.com'):
        # Remove periods from local part (Gmail ignores them)
        local_part = local_part.replace('.', '')
        # NOTE: Plus addressing (+tag) is preserved for email delivery

    return f"{local_part}@{domain}"


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
