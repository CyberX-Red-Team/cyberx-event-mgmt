"""Public API endpoints (no authentication required)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.workflow_service import WorkflowService
from app.services.event_service import EventService
from app.models.email_workflow import WorkflowTriggerEvent
from app.dependencies import get_db
from app.api.exceptions import not_found, bad_request, conflict
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
    If conflict exists, append incrementing numbers (1, 2, 3, etc.).

    Handles accented characters (é→e, ñ→n) and strips punctuation.
    """
    from app.utils.name_utils import sanitize_username
    base_username = sanitize_username(first_name, last_name)

    # Check if base username is available
    result = await db.execute(
        select(User).where(User.pandas_username == base_username)
    )
    if not result.scalar_one_or_none():
        return base_username

    # If conflict, try with incrementing numbers
    counter = 1
    while True:
        suffix = str(counter)
        max_base_len = 50 - len(suffix)
        candidate = f"{base_username[:max_base_len]}{suffix}"
        result = await db.execute(
            select(User).where(User.pandas_username == candidate)
        )
        if not result.scalar_one_or_none():
            return candidate
        counter += 1
        if counter > 999:
            import time
            timestamp = str(int(time.time()))[-6:]
            return f"{base_username[:44]}{timestamp}"


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
    age_attested = data.get("age_attested") is True
    future_contact = data.get("future_contact_consent") is True

    if not code or not terms_accepted:
        raise bad_request("Confirmation code and terms required")

    if not age_attested:
        raise bad_request("Please confirm the age statement to continue")

    result = await db.execute(
        select(User)
        .options(selectinload(User.role_obj))
        .where(User.confirmation_code == code)
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

    # Privacy choices recorded with the registration
    from app.services.consent_service import AGE_ATTESTATION_V1, set_future_contact_consent
    user.age_attestation = AGE_ATTESTATION_V1
    user.age_attested_at = now
    set_future_contact_consent(user, future_contact, now)

    # Update EventParticipation status to confirmed
    from app.models.event import EventParticipation, ParticipationStatus
    event_service = EventService(db)
    event = await event_service.get_current_event()

    participation = None
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

    # Set up event access (credentials, Keycloak sync, Discord invite, credentials email)
    from app.services.participant_service import ParticipantService
    await ParticipantService(db).activate_participation(user, event, participation, now)

    # Audit log (reuse event from above)
    audit_service = AuditService(db)

    await audit_service.log_terms_acceptance(
        user_id=user.id,
        event_id=event.id if event else 1,
        terms_version=terms_version,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    await audit_service.log(
        user_id=user.id,
        action="PRIVACY_CHOICES_RECORDED",
        resource_type="USER",
        resource_id=user.id,
        details={
            "source": "accept",
            "future_contact_consent": future_contact,
            "age_attestation": user.age_attestation,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
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
    from app.services.consent_service import DeclineChoice, set_future_contact_consent
    from app.services.invite_suppression_service import InviteSuppressionService

    code = data.get("confirmation_code")
    reason = data.get("reason", "")
    try:
        choice = DeclineChoice(data.get("future_contact_choice") or DeclineChoice.NOT_THIS_TIME.value)
    except ValueError:
        raise bad_request("Invalid choice")

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

    # The decliner's choice about what happens next. Declining is not itself a
    # do-not-contact request: only "don't invite me again" writes a suppression.
    set_future_contact_consent(user, choice == DeclineChoice.FUTURE_EVENTS, now)
    if choice == DeclineChoice.DO_NOT_INVITE:
        await InviteSuppressionService(db).add(user.email)

    # Update EventParticipation record
    event_service = EventService(db)
    event = await event_service.get_current_event()

    if event:
        from app.models.event import EventParticipation, ParticipationStatus
        ep_result = await db.execute(
            select(EventParticipation).where(
                EventParticipation.user_id == user.id,
                EventParticipation.event_id == event.id
            )
        )
        participation = ep_result.scalar_one_or_none()
        if participation:
            participation.status = ParticipationStatus.DECLINED.value
            participation.declined_at = now
            participation.responded_at = now
            participation.declined_reason = reason if reason else None

    await db.commit()
    await db.refresh(user)

    # Audit log
    audit_service = AuditService(db)

    await audit_service.log(
        user_id=user.id,
        action="DECLINE_PARTICIPATION",
        resource_type="USER",
        resource_id=user.id,
        details={
            "event_id": event.id if event else None,
            "event_name": event.name if event else None,
            "reason": reason,
            "future_contact_choice": choice.value,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    # Trigger decline notification workflow (if configured)
    workflow_service = WorkflowService(db)
    sponsor_vars = {}
    if user.sponsor_id:
        sponsor_result = await db.execute(
            select(User).where(User.id == user.sponsor_id)
        )
        sponsor = sponsor_result.scalar_one_or_none()
        if sponsor:
            last = sponsor.last_name or ""
            sponsor_vars = {
                "sponsor_first_name": sponsor.first_name or "",
                "sponsor_last_name": last,
                "sponsor_last_initial": f"{last[0]}." if last else "",
                "sponsor_name": f"{sponsor.first_name or ''} {last}".strip(),
                "sponsor_email": sponsor.email or "",
            }

    await workflow_service.trigger_workflow(
        trigger_event=WorkflowTriggerEvent.USER_DECLINED,
        user_id=user.id,
        custom_vars={
            "event_name": event.name if event else "CyberX Event",
            "decline_reason": reason if reason else "No reason provided",
            **sponsor_vars,
        }
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
