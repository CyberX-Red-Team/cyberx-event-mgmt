"""Deleting a person leaves no copy of their email or name anywhere,
except the printed name on CPE certificate records (kept for verification)."""
import pytest
from sqlalchemy import select

import app.models.participant_action  # noqa: F401  (register the table)
from app.models.audit_log import AuditLog
from app.models.cpe_certificate import CPECertificate
from app.models.password_sync_queue import PasswordSyncQueue
from app.models.user import User
from app.models.vpn import VPNCredential
from app.services.participant_service import ParticipantService
from app.services.personal_data_scrubber import _replace_identity
from tests.personal_data_seed import (
    MARK_EMAIL, MARK_FIRST, MARK_LAST, MARK_NAME, find_text, make_event, make_user,
    seed_person_everywhere,
)

pytestmark = pytest.mark.asyncio


async def _seeded(db):
    event = await make_event(db)
    person = await make_user(db, MARK_EMAIL, MARK_FIRST, MARK_LAST, pandas_username="mpers")
    await seed_person_everywhere(db, person, event)
    return person, event


async def test_delete_participant_removes_every_copy(db_session):
    person, _ = await _seeded(db_session)
    # Someone else whose legacy referrer-email field holds the person's address
    other = await make_user(db_session, "other@example.org", sponsor_email=MARK_EMAIL)

    assert await find_text(db_session, MARK_EMAIL)  # sanity: seeded everywhere

    assert await ParticipantService(db_session).delete_participant(person.id) is True
    db_session.expunge_all()

    assert await find_text(db_session, MARK_EMAIL) == []
    assert await find_text(db_session, "markerperson@example.org") == []  # normalized form
    name_hits = await find_text(db_session, MARK_NAME)
    assert all(h.startswith("cpe_certificates.user_name#") for h in name_hits), name_hits
    assert name_hits, "CPE certificate name must be kept for verification"

    other = await db_session.get(User, other.id)
    assert other.sponsor_email is None


async def test_rows_kept_for_security_and_certificates(db_session):
    person, _ = await _seeded(db_session)
    await ParticipantService(db_session).delete_participant(person.id)
    db_session.expunge_all()

    # Security log rows stay (minus identity), certificate record stays.
    logs = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any(log.action == "LOGIN_SUCCESS" and log.ip_address == "192.0.2.10" for log in logs)
    cpe = (await db_session.execute(select(CPECertificate))).scalar_one()
    assert cpe.certificate_number == "CPE-SEED-0001" and cpe.user_email is None
    # VPN config is kept but never recycled
    vpn = (await db_session.execute(select(VPNCredential))).scalar_one()
    assert vpn.is_available is False and vpn.assigned_to_username is None


async def test_keycloak_sync_rows_replaced_by_single_delete(db_session):
    person, _ = await _seeded(db_session)
    await ParticipantService(db_session).delete_participant(person.id)
    rows = (await db_session.execute(select(PasswordSyncQueue))).scalars().all()
    assert [(r.operation, r.synced, r.encrypted_password) for r in rows] == [
        ("delete_user", False, None)
    ]


async def test_audit_rows_of_other_people_untouched(db_session):
    person, _ = await _seeded(db_session)
    bystander = await make_user(db_session, "bystander@example.org", "Bea", "Stander")
    db_session.add(AuditLog(user_id=bystander.id, user_email=bystander.email,
                            user_name="Bea Stander", action="LOGIN_SUCCESS"))
    await db_session.commit()

    await ParticipantService(db_session).delete_participant(person.id)
    db_session.expunge_all()
    assert await find_text(db_session, "bystander@example.org")


async def test_user_delete_audit_records_ids_only(authenticated_admin_client, db_session):
    victim = await make_user(db_session, MARK_EMAIL, MARK_FIRST, MARK_LAST)
    resp = await authenticated_admin_client.delete(f"/api/admin/participants/{victim.id}")
    assert resp.status_code == 200
    db_session.expunge_all()
    assert await find_text(db_session, MARK_EMAIL) == []
    entry = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "USER_DELETE")
    )).scalar_one()
    assert entry.resource_id == victim.id


def test_replace_identity_walks_nested_json():
    value = {"a": [{"to": "X <marker.person@example.org>"}], "n": "Markerfirst Markerlast",
             "first": "Markerfirst", "count": 2}
    out, changed = _replace_identity(
        value, ["marker.person@example.org"], {"markerfirst markerlast"}
    )
    assert changed
    assert out == {"a": [{"to": "[deleted user]"}], "n": "[deleted user]",
                   "first": "Markerfirst", "count": 2}
