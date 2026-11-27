"""Seed one person's data into every table the personal-data registry covers.

Shared by the deletion (scrubber/retention) and export tests. Uses marker
values so tests can grep the whole database (or an export) for them.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, String, Text, select

from app.api.utils.validation import normalize_email
from app.database import Base
from app.models.audit_log import AuditLog, EmailEvent, VPNRequest
from app.models.cpe_certificate import CPECertificate
from app.models.email_queue import EmailQueue
from app.models.event import Event, EventParticipation
from app.models.instance import Instance
from app.models.participant_action import ParticipantAction
from app.models.password_sync_queue import PasswordSyncQueue
from app.models.redirector import Redirector
from app.models.session import Session
from app.models.tls_certificate import CAChain, TLSCertificate
from app.models.user import User
from app.models.vpn import VPNCredential

MARK_EMAIL = "Marker.Person@Example.org"
MARK_FIRST = "Markerfirst"
MARK_LAST = "Markerlast"
MARK_NAME = f"{MARK_FIRST} {MARK_LAST}"


async def make_user(db, email, first="Some", last="Person", **kw) -> User:
    user = User(
        email=email, email_normalized=normalize_email(email), first_name=first,
        last_name=last, country="USA", role=kw.pop("role", "invitee"), **kw,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def make_event(db, name="Seed Event", **kw) -> Event:
    from app.models.event import generate_slug
    event = Event(name=name, slug=generate_slug(name), year=kw.pop("year", 2026), **kw)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def seed_person_everywhere(db, user: User, event: Event) -> None:
    """One row per registry table for `user`, with identity copies everywhere."""
    now = datetime.now(timezone.utc)
    email, name = user.email, f"{user.first_name} {user.last_name}"
    ca = CAChain(name="seed-ca", event_id=event.id)
    db.add(ca)
    await db.flush()
    db.add_all([
        EventParticipation(user_id=user.id, event_id=event.id, status="confirmed",
                           declined_reason="seed reason"),
        Session(session_token="seed-session-token", user_id=user.id,
                expires_at=now + timedelta(hours=1), ip_address="192.0.2.10", user_agent="SeedUA"),
        PasswordSyncQueue(user_id=user.id, username="mpers", operation="create_user",
                          encrypted_password="seed-encrypted", synced=True, synced_at=now),
        AuditLog(user_id=user.id, user_email=email, user_name=name, action="LOGIN_SUCCESS",
                 ip_address="192.0.2.10", user_agent="SeedUA"),
        AuditLog(user_id=None, action="CREATE_INVITEE", resource_type="USER", resource_id=user.id,
                 details={"invitee_email": email, "invitee_name": name, "sponsor_id": 1}),
        AuditLog(user_id=None, action="SOMETHING_ELSE",
                 details={"nested": {"to": [email.upper()]}, "count": 3}),
        EmailEvent(user_id=user.id, email_to=email, event_type="delivered",
                   payload={"email": email, "event": "delivered"}),
        EmailQueue(user_id=user.id, template_name="invite", recipient_email=email,
                   recipient_name=name, custom_vars={"email": email}, status="sent"),
        VPNRequest(user_id=user.id, user_email=email, user_name=name, key_type="cyber"),
        VPNCredential(interface_ip="10.0.0.2", private_key="SEED-PRIVATE-KEY", endpoint="vpn:51820",
                      key_type="cyber", assigned_to_user_id=user.id, assigned_to_email=email,
                      assigned_to_name=name, assigned_to_username="mpers"),
        Instance(name="seed-instance", image_id="img", assigned_to_user_id=user.id,
                 assigned_to_email=email, assigned_to_name=name),
        ParticipantAction(user_id=user.id, event_id=event.id, action_type="custom",
                          title="Seed action", user_email=email, user_name=name,
                          response_note=f"note from {email}"),
        CPECertificate(user_id=user.id, user_email=email, user_name=name, event_id=event.id,
                       certificate_number="CPE-SEED-0001"),
        Redirector(id="seed-redirector", name="seed-redir", current_ip="192.0.2.20",
                   ssh_username="root", ssh_private_key="SEED-SSH-KEY", owner_id=user.id),
    ])
    await db.flush()
    db.add(TLSCertificate(user_id=user.id, user_email=email, user_name=name, event_id=event.id,
                          ca_chain_id=ca.id, common_name="seed.example.org"))
    await db.commit()


async def find_text(db, needle: str) -> list[str]:
    """Every table.column (and row id) whose text/JSON value contains `needle`."""
    needle = needle.lower()
    hits = []
    for table in Base.metadata.tables.values():
        cols = [c for c in table.columns if isinstance(c.type, (String, Text, JSON))]
        if not cols:
            continue
        pk = list(table.primary_key.columns)[0]
        rows = (await db.execute(select(pk, *cols))).all()
        for row in rows:
            for col, value in zip(cols, row[1:]):
                if value is not None and needle in str(value).lower():
                    hits.append(f"{table.name}.{col.name}#{row[0]}")
    return hits
