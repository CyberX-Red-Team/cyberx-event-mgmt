"""Form-body parsing through the real multipart parser.

Nothing else in the suite sends a form body, so a change to python-multipart or
to starlette's form handling would otherwise pass CI without the parser ever
running. These drive the form-accepting routes through the actual parser and
assert on what arrived, not just on the status code.
"""
import io
import zipfile

import pytest
from sqlalchemy import select

from app.models.instance import Instance
from app.services.vpn_import_service import VPNImportService


pytestmark = [pytest.mark.integration]


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("peer1.conf", "[Interface]\nPrivateKey = test-key\nAddress = 10.0.0.2/32\n")
    return buf.getvalue()


async def _reload_instance(db_session, instance_id: int) -> Instance:
    db_session.expire_all()
    result = await db_session.execute(select(Instance).where(Instance.id == instance_id))
    return result.scalar_one()


@pytest.fixture
async def owned_instance(db_session, invitee_user):
    """A private instance created by the invitee, so they may update it."""
    instance = Instance(
        name="form-parsing-test",
        image_id="test-image",
        created_by_user_id=invitee_user.id,
        visibility="private",
    )
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(instance)
    return instance


class TestMultipartFileUpload:
    """POST /api/vpn/import takes a multipart file upload."""

    @pytest.mark.asyncio
    async def test_file_bytes_and_filename_arrive_intact(
        self, authenticated_admin_client, monkeypatch
    ):
        """Only the storage call is stubbed; the route and parser are real."""
        captured = {}

        class _Job:
            id = 1
            status = "PENDING"

        async def fake_stage_upload(self, *, zip_bytes, filename, **kwargs):
            captured["bytes"] = zip_bytes
            captured["filename"] = filename
            return _Job()

        monkeypatch.setattr(VPNImportService, "stage_upload", fake_stage_upload)
        payload = _zip_bytes()

        response = await authenticated_admin_client.post(
            "/api/vpn/import",
            files={"file": ("configs.zip", payload, "application/zip")},
        )

        assert response.status_code == 200, response.text
        assert captured["filename"] == "configs.zip"
        assert captured["bytes"] == payload

    @pytest.mark.asyncio
    async def test_filename_is_parsed_from_the_part_headers(self, authenticated_admin_client):
        """A non-.zip filename is rejected by the handler, which proves it was read."""
        response = await authenticated_admin_client.post(
            "/api/vpn/import",
            files={"file": ("configs.txt", b"not a zip", "text/plain")},
        )

        assert response.status_code == 400
        assert "ZIP" in response.json()["detail"]


class TestFormFields:
    """PATCH /api/participants/instances/{id} takes plain form fields."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("encoding", ["urlencoded", "multipart"])
    async def test_fields_are_parsed_and_stored(
        self, encoding, authenticated_invitee_client, db_session, owned_instance
    ):
        kwargs = {"data": {"visibility": "public", "notes": "hello from a form"}}
        if encoding == "multipart":
            # A files entry makes httpx send multipart/form-data instead.
            kwargs["files"] = {"unused": ("unused.txt", b"", "text/plain")}

        response = await authenticated_invitee_client.patch(
            f"/api/participants/instances/{owned_instance.id}", **kwargs
        )

        assert response.status_code == 200, response.text
        stored = await _reload_instance(db_session, owned_instance.id)
        assert stored.visibility == "public"
        assert stored.notes == "hello from a form"

    @pytest.mark.asyncio
    async def test_semicolon_is_not_a_field_separator(
        self, authenticated_invitee_client, db_session, owned_instance
    ):
        """CVE-2026-53538: python-multipart < 0.0.30 split urlencoded bodies on ';'.

        Under the old parser this body yields visibility='public' plus a
        smuggled notes field. Under the fixed parser it is one field whose
        value is not a valid visibility, so the handler rejects it.
        """
        response = await authenticated_invitee_client.patch(
            f"/api/participants/instances/{owned_instance.id}",
            content=b"visibility=public;notes=smuggled",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        assert response.status_code == 400, response.text
        stored = await _reload_instance(db_session, owned_instance.id)
        assert stored.visibility == "private"
        assert stored.notes != "smuggled"
