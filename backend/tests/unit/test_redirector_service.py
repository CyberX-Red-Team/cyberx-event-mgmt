"""Unit tests for RedirectorService CRUD operations.

Tests run against in-memory SQLite using the shared conftest fixtures.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.redirector_service import (
    RedirectorService,
    StreamSniCollisionError,
    NoBridgePortAvailableError,
)
from app.services.nginx_config_service import SNI_BRIDGE_PORT_MIN, SNI_BRIDGE_PORT_MAX
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
    async def test_clear_byod_key(self, db_session: AsyncSession):
        """clear_byod_key removes BYOD credentials and switches to infra key."""
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "switch-redir",
            "current_ip": "10.0.0.14",
            "ssh_username": "debian",
            "ssh_private_key": VALID_PEM,
            "ssh_key_passphrase": "pass123",
        })

        assert redir.use_infrastructure_key is False
        assert redir.ssh_private_key is not None

        redir = await svc.clear_byod_key(redir)

        assert redir.use_infrastructure_key is True
        assert redir.ssh_private_key is None
        assert redir.ssh_key_passphrase is None

    @pytest.mark.asyncio
    async def test_create_with_instance_id(self, db_session: AsyncSession):
        """CyberX redirector with instance_id auto-sets use_infrastructure_key."""
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "cx-redir",
            "current_ip": "10.0.0.15",
            "ssh_username": "root",
            "instance_id": 999,
        })

        assert redir.use_infrastructure_key is True
        assert redir.instance_id == 999
        assert redir.ssh_private_key is None

    @pytest.mark.asyncio
    async def test_get_redirector_by_instance_id(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await svc.create_redirector({
            "name": "cx-redir-lookup",
            "current_ip": "10.0.0.16",
            "ssh_username": "root",
            "instance_id": 888,
        })

        found = await svc.get_redirector_by_instance_id(888)
        assert found is not None
        assert found.id == redir.id

        not_found = await svc.get_redirector_by_instance_id(777)
        assert not_found is None


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


# ---------------------------------------------------------------------------
# SNI routing: allocator, collision rules, CRUD
# ---------------------------------------------------------------------------

_SNI_STREAM_COMMON = dict(
    name="beacon",
    listen_port=443,
    cs_ip="10.0.0.200",
    cs_port=443,
    ssl_enabled=True,
    ssl_cert_path="/etc/ssl/certs/legit.pem",
    ssl_key_path="/etc/ssl/private/legit.key",
)


async def _new_redirector(svc: RedirectorService, name: str, ip: str):
    return await svc.create_redirector({
        "name": name,
        "current_ip": ip,
        "ssh_username": "debian",
        "ssh_private_key": VALID_PEM,
    })


@pytest.mark.unit
class TestSniStreamCreate:
    """Stream create path with SNI hostname + bridge port allocation."""

    @pytest.mark.asyncio
    async def test_legacy_stream_has_no_sni_fields(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "legacy-sni-1", "10.0.0.50")
        s = await svc.create_stream(redir.id, {
            "name": "legacy",
            "listen_port": 80,
            "cs_ip": "10.0.0.100",
            "cs_port": 80,
        })
        assert s.sni_hostname is None
        assert s.internal_bridge_port is None
        assert s.is_sni_routed is False

    @pytest.mark.asyncio
    async def test_sni_stream_gets_bridge_port_allocated(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "sni-alloc-1", "10.0.0.51")
        s = await svc.create_stream(redir.id, {
            **_SNI_STREAM_COMMON,
            "sni_hostname": "beacon.example.com",
        })
        assert s.sni_hostname == "beacon.example.com"
        assert s.internal_bridge_port == SNI_BRIDGE_PORT_MIN  # first free
        assert s.is_sni_routed is True

    @pytest.mark.asyncio
    async def test_sni_stream_requires_ssl(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "sni-no-ssl", "10.0.0.52")
        with pytest.raises(ValueError, match="ssl_enabled"):
            await svc.create_stream(redir.id, {
                "name": "bad-sni",
                "listen_port": 443,
                "cs_ip": "10.0.0.100",
                "cs_port": 443,
                "sni_hostname": "beacon.example.com",
                "ssl_enabled": False,
            })

    @pytest.mark.asyncio
    async def test_sni_stream_requires_cert_paths(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "sni-no-cert", "10.0.0.53")
        with pytest.raises(ValueError, match="ssl_cert_path"):
            await svc.create_stream(redir.id, {
                "name": "bad-sni",
                "listen_port": 443,
                "cs_ip": "10.0.0.100",
                "cs_port": 443,
                "sni_hostname": "beacon.example.com",
                "ssl_enabled": True,
                # No cert/key paths
            })

    @pytest.mark.asyncio
    async def test_bridge_ports_allocated_sequentially(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "sni-seq", "10.0.0.54")
        s1 = await svc.create_stream(redir.id, {
            **_SNI_STREAM_COMMON, "name": "a", "sni_hostname": "a.example.com",
        })
        s2 = await svc.create_stream(redir.id, {
            **_SNI_STREAM_COMMON, "name": "b", "sni_hostname": "b.example.com",
        })
        s3 = await svc.create_stream(redir.id, {
            **_SNI_STREAM_COMMON, "name": "c", "sni_hostname": "c.example.com",
        })
        ports = sorted([s1.internal_bridge_port, s2.internal_bridge_port, s3.internal_bridge_port])
        assert ports == [SNI_BRIDGE_PORT_MIN, SNI_BRIDGE_PORT_MIN + 1, SNI_BRIDGE_PORT_MIN + 2]

    @pytest.mark.asyncio
    async def test_bridge_ports_scoped_per_redirector(self, db_session: AsyncSession):
        """Two redirectors each get their own port pool — no global collisions."""
        svc = RedirectorService(db_session)
        r1 = await _new_redirector(svc, "sni-r1", "10.0.0.55")
        r2 = await _new_redirector(svc, "sni-r2", "10.0.0.56")
        s1 = await svc.create_stream(r1.id, {
            **_SNI_STREAM_COMMON, "sni_hostname": "one.example.com",
        })
        s2 = await svc.create_stream(r2.id, {
            **_SNI_STREAM_COMMON, "sni_hostname": "two.example.com",
        })
        assert s1.internal_bridge_port == SNI_BRIDGE_PORT_MIN
        assert s2.internal_bridge_port == SNI_BRIDGE_PORT_MIN


@pytest.mark.unit
class TestSniCollisionRules:
    """A given listen_port is either legacy-only or SNI-only per redirector."""

    @pytest.mark.asyncio
    async def test_legacy_blocks_new_sni_on_same_port(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "col-1", "10.0.0.60")
        await svc.create_stream(redir.id, {
            "name": "legacy", "listen_port": 443,
            "cs_ip": "10.0.0.100", "cs_port": 443,
        })
        with pytest.raises(StreamSniCollisionError, match="non-SNI"):
            await svc.create_stream(redir.id, {
                **_SNI_STREAM_COMMON,
                "sni_hostname": "beacon.example.com",
            })

    @pytest.mark.asyncio
    async def test_sni_blocks_new_legacy_on_same_port(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "col-2", "10.0.0.61")
        await svc.create_stream(redir.id, {
            **_SNI_STREAM_COMMON, "sni_hostname": "beacon.example.com",
        })
        with pytest.raises(StreamSniCollisionError, match="SNI-routed"):
            await svc.create_stream(redir.id, {
                "name": "legacy-too-late", "listen_port": 443,
                "cs_ip": "10.0.0.100", "cs_port": 443,
            })

    @pytest.mark.asyncio
    async def test_legacy_blocks_duplicate_legacy_on_same_port(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "col-3", "10.0.0.62")
        await svc.create_stream(redir.id, {
            "name": "legacy-a", "listen_port": 443,
            "cs_ip": "10.0.0.100", "cs_port": 443,
        })
        with pytest.raises(StreamSniCollisionError):
            await svc.create_stream(redir.id, {
                "name": "legacy-b", "listen_port": 443,
                "cs_ip": "10.0.0.101", "cs_port": 443,
            })

    @pytest.mark.asyncio
    async def test_multiple_sni_on_same_port_allowed(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "col-4", "10.0.0.63")
        await svc.create_stream(redir.id, {
            **_SNI_STREAM_COMMON, "sni_hostname": "alpha.example.com",
        })
        await svc.create_stream(redir.id, {
            **_SNI_STREAM_COMMON, "sni_hostname": "beta.example.com",
        })
        streams = await svc.list_streams(redir.id)
        assert len(streams) == 2
        assert {s.sni_hostname for s in streams} == {"alpha.example.com", "beta.example.com"}


@pytest.mark.unit
class TestSniStreamUpdate:
    @pytest.mark.asyncio
    async def test_rename_sni_hostname_keeps_bridge_port(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "upd-1", "10.0.0.70")
        s = await svc.create_stream(redir.id, {
            **_SNI_STREAM_COMMON, "sni_hostname": "old.example.com",
        })
        original_port = s.internal_bridge_port
        updated = await svc.update_stream(s, {"sni_hostname": "new.example.com"})
        assert updated.sni_hostname == "new.example.com"
        assert updated.internal_bridge_port == original_port  # port reused

    @pytest.mark.asyncio
    async def test_toggle_legacy_to_sni_rejected(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "upd-2", "10.0.0.71")
        s = await svc.create_stream(redir.id, {
            "name": "legacy", "listen_port": 8080,
            "cs_ip": "10.0.0.100", "cs_port": 8080,
        })
        with pytest.raises(StreamSniCollisionError, match="Cannot toggle"):
            await svc.update_stream(s, {"sni_hostname": "new.example.com"})

    @pytest.mark.asyncio
    async def test_toggle_sni_to_legacy_rejected(self, db_session: AsyncSession):
        svc = RedirectorService(db_session)
        redir = await _new_redirector(svc, "upd-3", "10.0.0.72")
        s = await svc.create_stream(redir.id, {
            **_SNI_STREAM_COMMON, "sni_hostname": "a.example.com",
        })
        with pytest.raises(StreamSniCollisionError, match="Cannot toggle"):
            await svc.update_stream(s, {"sni_hostname": None})
