"""Export entry points: admin (download / emailed link), self-service, guardian."""
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.email_queue import EmailQueue
from tests.personal_data_seed import make_user

pytestmark = pytest.mark.asyncio


def zip_data(content: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return json.loads(z.read("data.json"))["data"]


async def test_admin_download(authenticated_admin_client, db_session):
    person = await make_user(db_session, "person@example.org", "Pat", "Person")
    resp = await authenticated_admin_client.post(f"/api/admin/participants/{person.id}/export",
                                                 json={"delivery": "download"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    assert "cyberx-red-team-data-" in resp.headers["content-disposition"]
    assert zip_data(resp.content)["users"][0]["email"] == "person@example.org"
    entry = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "DATA_EXPORT_CREATED"))).scalar_one()
    assert entry.details == {"target_user_id": person.id, "delivery": "download"}
    assert entry.resource_id == person.id


async def test_admin_email_refused_where_storage_unavailable(authenticated_admin_client, db_session):
    person = await make_user(db_session, "person@example.org")
    resp = await authenticated_admin_client.post(f"/api/admin/participants/{person.id}/export",
                                                 json={"delivery": "email"})
    assert resp.status_code == 400 and "Download instead" in resp.json()["detail"]
    assert (await db_session.execute(select(EmailQueue))).first() is None


async def test_admin_email_goes_to_address_on_file_only(authenticated_admin_client, db_session, monkeypatch):
    stored = {}
    monkeypatch.setattr("app.services.data_export_service.email_delivery_available", lambda: True)
    monkeypatch.setattr("app.utils.r2_client.R2Client.put_object",
                        lambda self, key, data, content_type="": stored.update({key: data}) or True)
    monkeypatch.setattr("app.services.download_service.DownloadService.generate_link",
                        lambda self, key, expires_in=None: f"https://files.example/{key}?exp={expires_in}")
    person = await make_user(db_session, "Person@Example.org", "Pat", "Person")
    # A typed-in address is ignored: the request has no way to name a recipient
    resp = await authenticated_admin_client.post(f"/api/admin/participants/{person.id}/export",
                                                 json={"delivery": "email", "email": "attacker@example.net"})
    assert resp.status_code == 200, resp.text
    [key] = stored
    assert key.startswith(f"exports/{person.id}/") and key.endswith(".zip")
    q = (await db_session.execute(select(EmailQueue))).scalar_one()
    assert q.template_name == "data_export_ready" and q.recipient_email == "Person@Example.org"
    assert q.custom_vars["download_url"].endswith(f"?exp={7 * 86400}")
    entry = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "DATA_EXPORT_CREATED"))).scalar_one()
    assert entry.details == {"target_user_id": person.id, "delivery": "email"}


async def test_admin_export_forbidden_for_referrers(authenticated_sponsor_client, db_session, sponsor_user):
    invitee = await make_user(db_session, "mine@example.org", sponsor_id=sponsor_user.id)
    resp = await authenticated_sponsor_client.post(f"/api/admin/participants/{invitee.id}/export",
                                                   json={"delivery": "download"})
    assert resp.status_code == 403


async def test_self_service_returns_only_own_data_and_rate_limits(authenticated_invitee_client, db_session,
                                                                  invitee_user):
    await make_user(db_session, "someone.else@example.org")
    resp = await authenticated_invitee_client.post("/api/user/export")
    assert resp.status_code == 200, resp.text
    data = zip_data(resp.content)
    assert [u["email"] for u in data["users"]] == [invitee_user.email]
    assert b"someone.else@example.org" not in resp.content
    again = await authenticated_invitee_client.post("/api/user/export")
    assert again.status_code == 429


async def test_guardian_downloads_only_linked_minor(client, db_session, active_event):
    from app.utils.security import hash_password
    guardian = await make_user(db_session, "parent@example.org", "Pat", "Parent",
                               password_hash=hash_password("pw-12345"))
    minor = await make_user(db_session, "kid@example.org", "Kim", "Kid", guardian_user_id=guardian.id,
                            guardian_link_status="confirmed",
                            adult_on=date(date.today().year + 1, date.today().month, 1))
    stranger = await make_user(db_session, "other@example.org")
    r = await client.post("/api/auth/login", json={"username": guardian.email, "password": "pw-12345"})
    client.cookies.set("session_token", r.cookies.get("session_token"))
    ok = await client.post(f"/api/guardian/minors/{minor.id}/export")
    assert ok.status_code == 200, ok.text
    assert zip_data(ok.content)["users"][0]["email"] == "kid@example.org"
    assert (await client.post(f"/api/guardian/minors/{stranger.id}/export")).status_code == 403
    assert (await client.post(f"/api/guardian/minors/{minor.id}/export")).status_code == 429


async def test_export_cleanup_skipped_without_storage_and_deletes_old_files(db_session, test_settings,
                                                                           monkeypatch):
    from app.services.retention_service import RetentionService
    assert (await RetentionService(db_session, settings=test_settings).purge_old_exports(False))["skipped"]

    now = datetime.now(timezone.utc)
    deleted = []
    settings = test_settings.model_copy(update={
        "R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "b", "R2_SECRET_ACCESS_KEY": "c", "R2_BUCKET": "d"})
    monkeypatch.setattr("app.utils.r2_client.R2Client.from_settings", classmethod(lambda cls: cls("a", "b", "c", "d")))
    monkeypatch.setattr("app.utils.r2_client.R2Client.list_objects", lambda self, prefix: [
        ("exports/1/old.zip", now - timedelta(days=31)), ("exports/1/new.zip", now - timedelta(days=29))])
    monkeypatch.setattr("app.utils.r2_client.R2Client.delete_object", lambda self, key: deleted.append(key) or True)
    service = RetentionService(db_session, settings=settings, now=now)
    assert await service.purge_old_exports(dry_run=True) == {"deleted": 1} and deleted == []
    assert await service.purge_old_exports(dry_run=False) == {"deleted": 1}
    assert deleted == ["exports/1/old.zip"]

    monkeypatch.setenv("STAGING_STUB_EXTERNALS", "true")  # staging: never touch the shared bucket
    assert (await service.purge_old_exports(False))["skipped"]
