"""Personal-data export: complete, no secrets, nobody else's data."""
import io
import json
import zipfile

import pytest

import app.models.participant_action  # noqa: F401
from app.models.audit_log import AuditLog
from app.models.cpe_certificate import CPECertificate
from app.models.email_queue import EmailQueue
from app.models.guardian_consent import GuardianConsent
from app.models.invite_suppression import InviteSuppression
from app.services.data_export_service import DataExportService
from app.services.invite_suppression_service import email_hmac
from app.services.personal_data_registry import REGISTRY
from tests.personal_data_seed import (
    MARK_EMAIL, MARK_FIRST, MARK_LAST, make_event, make_user, seed_person_everywhere,
)

pytestmark = pytest.mark.asyncio

REFERRER_EMAIL = "referrer.marker@example.net"
GUARDIAN_EMAIL = "guardian.marker@example.net"
BYSTANDER_EMAIL = "bystander.marker@example.net"
SECRETS = {
    "password_hash": "$2b$12$SECRETHASHMARKER",
    "pandas_password": "SECRET-EVENT-PASSWORD",
    "confirmation_code": "SECRET-CONFIRM-CODE",
    "password_reset_token": "SECRET-RESET-TOKEN",
}
SEEDED_SECRETS = ["seed-session-token", "SEED-PRIVATE-KEY", "SEED-SSH-KEY", "seed-encrypted"]


def unzip(blob: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return {n: z.read(n) for n in z.namelist()}


def all_text(files: dict[str, bytes]) -> str:
    return "\n".join(v.decode("utf-8", "replace") for v in files.values()).lower()


async def _operator(db, monkeypatch):
    """A fully onboarded operator with data in every registry table."""
    event = await make_event(db, "Export Event")
    referrer = await make_user(db, REFERRER_EMAIL, "Rita", "Referrer", role="sponsor")
    guardian = await make_user(db, GUARDIAN_EMAIL, "Gary", "Guardian")
    person = await make_user(db, MARK_EMAIL, MARK_FIRST, MARK_LAST, sponsor_id=referrer.id,
                             guardian_user_id=guardian.id, guardian_link_status="confirmed",
                             sponsor_email=REFERRER_EMAIL, password_hash=SECRETS["password_hash"],
                             confirmation_code=SECRETS["confirmation_code"],
                             password_reset_token=SECRETS["password_reset_token"],
                             pandas_username="mpers", decline_reason="busy that week")
    person.pandas_password = SECRETS["pandas_password"]
    await db.commit()
    await seed_person_everywhere(db, person, event)
    db.add_all([
        # An admin acted on the person's account (their IP mustn't appear)
        AuditLog(user_id=referrer.id, action="UPDATE_INVITEE", resource_type="USER", resource_id=person.id,
                 ip_address="198.51.100.77", user_agent="ReferrerBrowser",
                 details={"invitee_email": MARK_EMAIL, "sponsor_name": "Rita Referrer",
                          "cc": BYSTANDER_EMAIL, "template_name": "invite"}),
        # A guardian's copy of the person's email
        EmailQueue(user_id=person.id, template_name="logistics", recipient_email=GUARDIAN_EMAIL,
                   recipient_name="Gary Guardian", status="sent"),
        GuardianConsent(minor_user_id=person.id, guardian_user_id=guardian.id, event_id=event.id,
                        relationship_type="parent", guardian_name_typed="Gary Guardian",
                        consent_text_version="v1", ip_address="203.0.113.9", user_agent="GuardianBrowser"),
    ])
    cpe = (await db.execute(__import__("sqlalchemy").select(CPECertificate))).scalar_one()
    cpe.pdf_storage_key = "cpe/CPE-SEED-0001.pdf"
    await db.commit()
    monkeypatch.setattr("app.utils.r2_client.R2Client.get_object",
                        lambda self, key: b"%PDF-1.4 seed certificate" if key == cpe.pdf_storage_key else None)
    return person, referrer, guardian


async def test_full_export_covers_every_registry_source(db_session, monkeypatch):
    person, _, _ = await _operator(db_session, monkeypatch)
    name, blob = await DataExportService(db_session).export_user(person.id)
    assert name.startswith("cyberx-red-team-data-") and name.endswith(".zip")
    files = unzip(blob)
    assert {"README.txt", "data.json", "summary.html", "certificates/CPE-SEED-0001.pdf"} <= set(files)
    data = json.loads(files["data.json"])["data"]
    exportable = {s.key for s in REGISTRY if s.subject_columns and s.export_columns}
    assert set(data) == exportable
    empty = [k for k in exportable if not data[k]]
    assert not empty, f"sources with no rows for a fully seeded person: {empty}"
    profile = data["users"][0]
    assert profile["email"] == MARK_EMAIL and profile["decline_reason"] == "busy that week"
    assert profile["referred_by"] == "Rita Referrer" and profile["parent_or_guardian"] == "Gary Guardian"
    assert data["event_participations"][0]["event_name"] == "Export Event"


async def test_no_secrets_anywhere_in_the_zip(db_session, monkeypatch):
    person, _, _ = await _operator(db_session, monkeypatch)
    _, blob = await DataExportService(db_session).export_user(person.id)
    text = all_text(unzip(blob))
    for marker in list(SECRETS.values()) + SEEDED_SECRETS:
        assert marker.lower() not in text, f"secret leaked: {marker}"


async def test_no_other_persons_contact_details(db_session, monkeypatch):
    person, _, _ = await _operator(db_session, monkeypatch)
    _, blob = await DataExportService(db_session).export_user(person.id)
    files = unzip(blob)
    text = all_text(files)
    for other in (REFERRER_EMAIL, GUARDIAN_EMAIL, BYSTANDER_EMAIL, "198.51.100.77", "referrerbrowser",
                  "203.0.113.9", "guardianbrowser"):
        assert other.lower() not in text, f"other person's data: {other}"
    data = json.loads(files["data.json"])["data"]
    entry = next(a for a in data["audit_logs"] if a["action"] == "UPDATE_INVITEE")
    assert entry["performed_by"] == "another user"
    assert entry["details"]["sponsor_name"] == "another user" and entry["details"]["cc"] == "another user"
    assert entry["details"]["template_name"] == "invite"  # not a person's name
    assert entry["details"]["invitee_email"] == MARK_EMAIL  # the person's own data stays
    assert all(e["recipient_email"] == MARK_EMAIL for e in data["email_queue"])  # guardian copy filtered


async def test_never_registered_invitee(db_session):
    event = await make_event(db_session, "Their Event")
    person = await make_user(db_session, "never.registered@example.org", "Nev", "Er", confirmed="NO",
                             decline_reason="not this year")
    from app.models.event import EventParticipation
    db_session.add(EventParticipation(user_id=person.id, event_id=event.id, status="declined",
                                      declined_reason="not this year"))
    await db_session.commit()
    _, blob = await DataExportService(db_session).export_user(person.id)
    data = json.loads(unzip(blob)["data.json"])["data"]
    assert data["users"][0]["email"] == "never.registered@example.org"
    assert data["event_participations"][0]["declined_reason"] == "not this year"


async def test_readme_mentions_do_not_invite_entry_only_when_present(db_session):
    person = await make_user(db_session, "blocked@example.org")
    _, blob = await DataExportService(db_session).export_user(person.id)
    assert b"Do-not-invite list" not in unzip(blob)["README.txt"]
    db_session.add(InviteSuppression(email_hmac=email_hmac(person.email)))
    await db_session.commit()
    _, blob = await DataExportService(db_session).export_user(person.id, link_expiry_days=7)
    readme = unzip(blob)["README.txt"].decode()
    assert "Do-not-invite list" in readme and "7 days" in readme and "hello@cyberxredteam.org" in readme


async def test_summary_html_escapes_and_has_no_external_assets(db_session):
    person = await make_user(db_session, "x@example.org", "<script>alert(1)</script>", "Last")
    _, blob = await DataExportService(db_session).export_user(person.id)
    page = unzip(blob)["summary.html"].decode()
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "http://" not in page and "https://" not in page.replace("https://cyberxredteam.org", "")


# ----------------------------------------------------------- registry rules

SECRET_COLUMNS = {
    "password_hash", "pandas_password", "password_phonetic", "password_reset_token", "confirmation_code",
    "session_token", "private_key", "preshared_key", "ssh_private_key", "ssh_key_passphrase",
    "agent_token_hash", "vpn_config_token", "encrypted_password", "discord_invite_code", "custom_vars",
    "payload", "permission_overrides", "sponsor_email", "guardian_email_pending", "cert_bundle_r2_key",
    "private_key_r2_key", "r2_key", "pdf_storage_key", "notes", "issued_by_name", "revoked_by_name",
    "user_email",
}


@pytest.mark.parametrize("src", [s for s in REGISTRY if s.subject_columns], ids=lambda s: s.key)
def test_every_personal_source_is_exported_or_explained(src):
    assert src.export_columns or src.export_note, f"{src.key}: no export_columns and no export_note"
    assert set(src.export_columns) <= set(src.model.__table__.c.keys())


@pytest.mark.parametrize("src", REGISTRY, ids=lambda s: s.key)
def test_no_secret_or_staff_columns_in_exports(src):
    leaked = set(src.export_columns) & SECRET_COLUMNS
    assert not leaked, f"{src.key} exports {leaked}"
