"""Public API endpoints (no authentication required)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.workflow_service import WorkflowService
from app.services.event_service import EventService
from app.models.email_workflow import WorkflowTriggerEvent
from app.dependencies import get_db
from app.api.exceptions import not_found, forbidden, bad_request, conflict, unauthorized, server_error
import secrets
import string
import logging
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["Public"])

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def generate_username(first_name: str, last_name: str, db: AsyncSession) -> str:
    """
    Generate a unique username in the format: first_initial + last_name.
    If conflict exists, append incrementing numbers (2, 3, 4, etc.).

    Args:
        first_name: User's first name
        last_name: User's last name
        db: Database session

    Returns:
        Unique username
    """
    # Generate base username: first initial + last name (lowercase, no spaces)
    base_username = f"{first_name[0]}{last_name}".lower().replace(" ", "")

    # Check if base username is available
    result = await db.execute(
        select(User).where(User.pandas_username == base_username)
    )
    if not result.scalar_one_or_none():
        return base_username

    # If conflict, try with incrementing numbers
    counter = 2
    while True:
        candidate = f"{base_username}{counter}"
        result = await db.execute(
            select(User).where(User.pandas_username == candidate)
        )
        if not result.scalar_one_or_none():
            return candidate
        counter += 1


def generate_password(length: int = 12) -> str:
    """
    Generate a secure random password.

    Args:
        length: Password length (default 12)

    Returns:
        Random password with mix of uppercase, lowercase, digits, and symbols

    Uses a safe special character set that avoids mis-interpretation by:
    - HTML/email clients: no &, <, >, ", '
    - Handlebars templates: no { }
    - Shells: no !, $, `, \\, |, ;
    """
    safe_specials = "@#%^*"
    all_chars = string.ascii_letters + string.digits + safe_specials

    # Ensure at least one of each character type
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(safe_specials),
    ]
    chars.extend(secrets.choice(all_chars) for _ in range(length - 4))

    # Shuffle to avoid predictable patterns
    secrets.SystemRandom().shuffle(chars)
    return ''.join(chars)


def generate_phonetic_password(password: str) -> str:
    """
    Generate a phonetic representation of the password for easier communication.
    Uppercase letters are represented in UPPERCASE, lowercase in lowercase.

    Args:
        password: The password to convert

    Returns:
        Phonetic representation (e.g., "g" = "golf", "G" = "GOLF")
    """
    phonetic_map = {
        'A': 'Alpha', 'B': 'Bravo', 'C': 'Charlie', 'D': 'Delta', 'E': 'Echo',
        'F': 'Foxtrot', 'G': 'Golf', 'H': 'Hotel', 'I': 'India', 'J': 'Juliet',
        'K': 'Kilo', 'L': 'Lima', 'M': 'Mike', 'N': 'November', 'O': 'Oscar',
        'P': 'Papa', 'Q': 'Quebec', 'R': 'Romeo', 'S': 'Sierra', 'T': 'Tango',
        'U': 'Uniform', 'V': 'Victor', 'W': 'Whiskey', 'X': 'X-ray', 'Y': 'Yankee',
        'Z': 'Zulu',
        '0': 'Zero', '1': 'One', '2': 'Two', '3': 'Three', '4': 'Four',
        '5': 'Five', '6': 'Six', '7': 'Seven', '8': 'Eight', '9': 'Nine',
        '!': 'Exclamation', '@': 'At', '#': 'Hash', '$': 'Dollar',
        '%': 'Percent', '^': 'Caret', '&': 'Ampersand', '*': 'Asterisk'
    }

    phonetic = []
    for char in password:
        upper_char = char.upper()
        if upper_char in phonetic_map:
            word = phonetic_map[upper_char]
            # If original char was lowercase, make the phonetic word lowercase
            if char.islower():
                word = word.lower()
            # If original char was uppercase, make the phonetic word UPPERCASE
            elif char.isupper():
                word = word.upper()
            # Numbers and symbols keep their default capitalization
            phonetic.append(word)
        else:
            # For any other character, just include it as-is
            phonetic.append(char)

    return '-'.join(phonetic)

@router.get("/confirm/terms")
async def get_confirmation_terms(
    code: str,
    db: AsyncSession = Depends(get_db)
):
    """Get terms for confirmation (validates code)."""
    result = await db.execute(
        select(User).where(User.confirmation_code == code)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise not_found("Invalid confirmation code")

    if user.confirmed == 'YES':
        return {"already_confirmed": True}

    if user.confirmed == 'NO':
        return {"already_declined": True}

    event_service = EventService(db)
    event = await event_service.get_current_event()

    # Check if event is active
    if not event:
        return {
            "no_active_event": True,
            "user": {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email
            }
        }

    return {
        "user": {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email
        },
        "terms": {
            "content": event.terms_content,
            "version": event.terms_version
        },
        "event": {
            "name": event.name,
            "year": event.year
        }
    }


@router.post("/confirm/accept")
async def confirm_participation(
    request: Request,
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """Confirm participation and accept terms."""
    code = data.get("confirmation_code")
    terms_accepted = data.get("terms_accepted")
    terms_version = data.get("terms_version")

    if not code or not terms_accepted:
        raise bad_request("Confirmation code and terms required")

    result = await db.execute(
        select(User).where(User.confirmation_code == code)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise not_found("Invalid confirmation code")

    if user.confirmed == 'YES':
        raise conflict("Already confirmed")

    # Update user confirmation and terms
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    user.confirmed = 'YES'
    user.confirmed_at = now
    user.terms_accepted = True
    user.terms_accepted_at = now
    user.terms_version = terms_version

    # Update EventParticipation status to confirmed
    from app.models.event import EventParticipation, ParticipationStatus
    event_service = EventService(db)
    event = await event_service.get_current_event()

    if event:
        participation_result = await db.execute(
            select(EventParticipation).where(
                EventParticipation.user_id == user.id,
                EventParticipation.event_id == event.id
            )
        )
        participation = participation_result.scalar_one_or_none()

        if participation:
            participation.status = ParticipationStatus.CONFIRMED.value
            participation.confirmed_at = now
            participation.terms_accepted_at = now
            participation.terms_version_accepted = terms_version

    # Generate credentials if not already set
    # Username: Only generate if missing (returning participants keep their existing username)
    if not user.pandas_username:
        user.pandas_username = await generate_username(user.first_name, user.last_name, db)

    # Password: Different behavior based on role
    # - Invitees: Always generate new password each year (for security)
    # - Sponsors: Keep existing password across years (only generate if missing)
    should_generate_password = False
    password_generation_reason = None

    if user.role == 'invitee':
        should_generate_password = True  # Always generate new password for invitees
        password_generation_reason = "invitee role (always regenerate)"
    elif not user.pandas_password:
        should_generate_password = True  # Generate for sponsors only if missing
        password_generation_reason = f"missing password (role: {user.role}, has_encrypted: {user._pandas_password_encrypted is not None})"

    if should_generate_password:
        logger.info(
            f"Generating password during confirmation for user {user.id} ({user.email}, role: {user.role}). "
            f"Reason: {password_generation_reason}"
        )
        password = generate_password(12)
        user.pandas_password = password  # Store plaintext for email (will be synced to Keycloak)
        user.password_hash = pwd_context.hash(password)  # Store hash for local auth
        user.password_phonetic = generate_phonetic_password(password)  # For easy communication
    else:
        logger.info(
            f"Keeping existing password for user {user.id} ({user.email}, role: {user.role}) "
            f"during confirmation"
        )

    await db.commit()
    await db.refresh(user)

    # Audit log (reuse event from above)
    audit_service = AuditService(db)

    await audit_service.log_terms_acceptance(
        user_id=user.id,
        event_id=event.id if event else 1,
        terms_version=terms_version,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    # Trigger credentials email
    # Sponsors/admins already received credentials at account creation — skip resend.
    # Only send credentials on confirmation for invitees (or sponsors missing credentials).
    workflow_service = WorkflowService(db)
    if should_generate_password:
        await workflow_service.trigger_workflow(
            trigger_event=WorkflowTriggerEvent.USER_CONFIRMED,
            user_id=user.id,
            custom_vars={
                "login_url": "https://portal.cyberxredteam.org/login",
                "event_name": event.name if event else "CyberX 2026",
                "pandas_username": user.pandas_username,
                "pandas_password": user.pandas_password,
                "password_phonetic": user.password_phonetic
            }
        )
    else:
        logger.info(
            f"Skipping credential email for {user.role} {user.id} on confirmation — "
            f"credentials already sent at account creation"
        )

    return {
        "success": True,
        "message": "Participation confirmed!",
        "user": {"first_name": user.first_name, "email": user.email}
    }


@router.post("/confirm/decline")
async def decline_participation(
    request: Request,
    data: dict,
    db: AsyncSession = Depends(get_db)
):
    """Decline participation."""
    code = data.get("confirmation_code")
    reason = data.get("reason", "")

    if not code:
        raise bad_request("Confirmation code required")

    result = await db.execute(
        select(User).where(User.confirmation_code == code)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise not_found("Invalid confirmation code")

    if user.confirmed == 'NO':
        raise conflict("Already declined")

    # Update user confirmation status
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    user.confirmed = 'NO'
    user.confirmed_at = now
    user.decline_reason = reason if reason else None

    await db.commit()
    await db.refresh(user)

    # Audit log
    audit_service = AuditService(db)
    event_service = EventService(db)
    event = await event_service.get_current_event()

    await audit_service.log(
        user_id=user.id,
        action="DECLINE_PARTICIPATION",
        resource_type="USER",
        resource_id=user.id,
        details={
            "event_id": event.id if event else None,
            "event_name": event.name if event else None,
            "reason": reason
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    return {
        "success": True,
        "message": "Participation declined. Thank you for letting us know."
    }


@router.get("/countries")
async def get_countries():
    """
    Get list of supported countries with flag emojis.

    Returns list of countries for use in dropdown menus.
    No authentication required - public endpoint.
    """
    from app.countries import get_countries_list, DEFAULT_COUNTRY

    return {
        "countries": get_countries_list(),
        "default": DEFAULT_COUNTRY
    }
