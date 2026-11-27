"""Future-contact consent, decline choices and age attestation."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer

from app.config import get_settings
from app.models.user import User

# Age statement on the accept form (Privacy Policy "Age" section: minimum 16,
# 16-17 only with consent from a parent/guardian who also takes part).
AGE_ATTESTATION_V1 = "adult_or_guardian_consent_v1"

# Roles exempt from consent gating on automatic invitations (organizers/referrers).
STAFF_ROLES = ("admin", "sponsor")


class DeclineChoice(str, Enum):
    """What a decliner chose on the decline form (Privacy Policy "If someone referred you")."""
    NOT_THIS_TIME = "not_this_time"     # default: no consent; invitation details deleted after 12 months
    FUTURE_EVENTS = "future_events"     # consent: kept and invited next time
    DO_NOT_INVITE = "do_not_invite"     # do-not-invite entry; details deleted after 12 months


def set_future_contact_consent(user: User, consent: bool, now: Optional[datetime] = None) -> None:
    user.future_contact_consent = bool(consent)
    user.future_contact_consent_at = now or datetime.now(timezone.utc)


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().SECRET_KEY, salt="future-contact-withdraw-v1")


def make_withdraw_token(user_id: int) -> str:
    return _serializer().dumps({"u": user_id})


def read_withdraw_token(token: str) -> Optional[int]:
    try:
        data = _serializer().loads(token)
    except BadSignature:
        return None
    user_id = data.get("u") if isinstance(data, dict) else None
    return user_id if isinstance(user_id, int) else None


def withdraw_url(user_id: int) -> str:
    return f"{get_settings().FRONTEND_URL}/future-contact/withdraw?token={make_withdraw_token(user_id)}"


def auto_invite_allowed(user: User, invited_to_other_events: bool) -> bool:
    """
    May the automatic invitation run (event activation) invite this person?

    Explicit invitations by a referrer or admin (resend invite, new referral)
    don't go through this check: a referral is its own basis.
    """
    if user.role in STAFF_ROLES:
        return True
    if user.future_contact_consent is True:
        return True
    if user.future_contact_consent is False:
        return False
    # No choice recorded yet.
    if not invited_to_other_events:
        return True  # a new referral that hasn't had its first invitation yet
    # Record predates consent collection (2027 transition).
    return get_settings().LEGACY_FUTURE_INVITES_ENABLED


def may_receive_optional_email(user: User) -> bool:
    """Announcements / future-event emails: only with recorded consent (staff exempt)."""
    return user.role in STAFF_ROLES or user.future_contact_consent is True
