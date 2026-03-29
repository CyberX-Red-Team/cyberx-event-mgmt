"""Unit tests for RedirectorService CRUD operations.

Tests run against in-memory SQLite using the shared conftest fixtures.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.redirector_service import RedirectorService
from app.utils.encryption import init_encryptor, generate_encryption_key, encrypt_field, decrypt_field


VALID_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\ntestkey123\n-----END OPENSSH PRIVATE KEY-----"
VALID_PEM_2 = "-----BEGIN OPENSSH PRIVATE KEY-----\nnewkey456\n-----END OPENSSH PRIVATE KEY-----"


@pytest_asyncio.fixture(autouse=True)
async def _init_encryption(test_settings):
    """Ensure encryptor is initialized before each test."""
    init_encryptor(test_settings.ENCRYPTION_KEY)


@pytest.mark.unit
class TestRedirectorServiceCreate:
    """Test redirector creation."""

    @pytest.mark.asyncio
    async def test_create_byod_redirector(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "byod-redir-01",
            "current_ip": "10.0.0.1",
            "ssh_port": 22,
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
            "nginx_stream_dir": "/etc/nginx/stream.d",
        })

        assert redir.id is not None
        assert redir.name == "byod-redir-01"
        assert redir.use_infrastructure_key is False
        assert redir.ssh_private_key is not None
        # Verify key is encrypted (not plaintext)
        assert redir.ssh_private_key != VALID_PEM
        assert redir.status == "unknown"

    @pytest.mark.asyncio
    async def test_create_infra_key_redirector(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "infra-redir-01",
            "current_ip": "10.0.0.2",
            "ssh_username": "debian",
            "use_infrastructure_key": True,
        })

        assert redir.use_infrastructure_key is True
        assert redir.ssh_private_key is None
        assert redir.ssh_key_passphrase is None

    @pytest.mark.asyncio
    async def test_create_encrypts_key(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "enc-redir",
            "current_ip": "10.0.0.3",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
        })

        decrypted = svc.get_decrypted_key(redir)
        assert decrypted == VALID_PEM

    @pytest.mark.asyncio
    async def test_create_encrypts_passphrase(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "pass-redir",
            "current_ip": "10.0.0.4",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
            "ssh_key_passphrase": "my-passphrase",
        })

        decrypted = svc.get_decrypted_passphrase(redir)
        assert decrypted == "my-passphrase"

    @pytest.mark.asyncio
    async def test_no_passphrase_returns_none(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "nopass-redir",
            "current_ip": "10.0.0.5",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
        })

        assert svc.get_decrypted_passphrase(redir) is None


@pytest.mark.unit
class TestRedirectorServiceUpdate:
    """Test redirector update operations."""

    @pytest.mark.asyncio
    async def test_update_simple_fields(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "upd-redir",
            "current_ip": "10.0.0.10",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
        })

        updated = await svc.update_redirector(redir, {
            "name": "upd-redir-renamed",
            "current_ip": "10.0.0.11",
        })

        assert updated.name == "upd-redir-renamed"
        assert updated.current_ip == "10.0.0.11"

    @pytest.mark.asyncio
    async def test_update_replaces_key(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "key-redir",
            "current_ip": "10.0.0.12",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
        })

        await svc.update_redirector(redir, {"ssh_private_key": VALID_PEM_2})
        assert svc.get_decrypted_key(redir) == VALID_PEM_2

    @pytest.mark.asyncio
    async def test_update_keeps_key_when_omitted(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "keep-key-redir",
            "current_ip": "10.0.0.13",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
        })

        await svc.update_redirector(redir, {"name": "keep-key-renamed"})
        assert svc.get_decrypted_key(redir) == VALID_PEM

    @pytest.mark.asyncio
    async def test_switch_to_infra_key(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "switch-redir",
            "current_ip": "10.0.0.14",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
            "ssh_key_passphrase": "pass123",
        })

        assert redir.use_infrastructure_key is False
        await svc.update_redirector(redir, {"use_infrastructure_key": True})

        assert redir.use_infrastructure_key is True
        assert redir.ssh_private_key is None
        assert redir.ssh_key_passphrase is None

    @pytest.mark.asyncio
    async def test_switch_to_byod_key(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "switch-byod",
            "current_ip": "10.0.0.15",
            "ssh_username": "debian",
            "use_infrastructure_key": True,
        })

        assert redir.use_infrastructure_key is True
        await svc.update_redirector(redir, {
            "use_infrastructure_key": False,
            "ssh_private_key": VALID_PEM,
        })

        assert redir.use_infrastructure_key is False
        assert svc.get_decrypted_key(redir) == VALID_PEM


@pytest.mark.unit
class TestRedirectorServiceList:
    """Test list and query operations."""

    @pytest.mark.asyncio
    async def test_list_empty(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        result = await svc.list_redirectors()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_owner_filter(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        await svc.create_redirector({
            "name": "owned-redir",
            "current_ip": "10.0.0.20",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
            "owner_id": 42,
        })
        await svc.create_redirector({
            "name": "other-redir",
            "current_ip": "10.0.0.21",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
            "owner_id": 99,
        })

        owned = await svc.list_redirectors(owner_id=42)
        assert len(owned) == 1
        assert owned[0].name == "owned-redir"

        all_redirs = await svc.list_redirectors()
        assert len(all_redirs) == 2


@pytest.mark.unit
class TestRedirectorServiceDelete:
    """Test delete operations."""

    @pytest.mark.asyncio
    async def test_delete_redirector(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "del-redir",
            "current_ip": "10.0.0.30",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
        })

        await svc.delete_redirector(redir)
        assert await svc.get_redirector(redir.id) is None

    @pytest.mark.asyncio
    async def test_delete_cascades_streams(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "cascade-redir",
            "current_ip": "10.0.0.31",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
        })
        await svc.create_stream(redir.id, {
            "name": "test-stream",
            "listen_port": 443,
            "cs_ip": "10.0.0.100",
            "cs_port": 443,
        })

        streams_before = await svc.list_streams(redir.id)
        assert len(streams_before) == 1

        await svc.delete_redirector(redir)
        streams_after = await svc.list_streams(redir.id)
        assert len(streams_after) == 0


@pytest.mark.unit
class TestRedirectorServiceStatus:
    """Test status update operations."""

    @pytest.mark.asyncio
    async def test_update_status(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "status-redir",
            "current_ip": "10.0.0.40",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
        })

        assert redir.status == "unknown"
        await svc.update_status(redir, "online", os_info={"os": "Debian 12"})
        assert redir.status == "online"
        assert redir.os_info == {"os": "Debian 12"}
        assert redir.last_tested_at is not None

    @pytest.mark.asyncio
    async def test_update_deployed_at(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "deploy-redir",
            "current_ip": "10.0.0.41",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
        })

        assert redir.last_deployed_at is None
        await svc.update_deployed_at(redir)
        assert redir.last_deployed_at is not None
