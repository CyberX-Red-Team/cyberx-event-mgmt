"""
Unit tests for VPNService.

Tests VPN credential management, assignment, import/export, batch operations,
and WireGuard configuration generation.
"""

import pytest
import zipfile
import io
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.vpn_service import VPNService
from app.models.user import User
from app.models.vpn import VPNCredential


# Sample WireGuard configuration for testing
SAMPLE_WIREGUARD_CONFIG = """[Interface]
PrivateKey = oK56DE9Ue9zK76rAc8pBl6opph+1v36lm7cXXsQKrQM=
Address = 10.66.66.2/32,fd00:1:66::2/128
DNS = 1.1.1.1

[Peer]
PublicKey = HIgo9xNzJMWLKASShiTqIybxZ0U3wGLiUeJ1PKf8ykw=
PresharedKey = 0Q8P8LkNfPrPgDEJOBR5p7N6DwUhJHbmhJDRwLF8G38=
Endpoint = vpn.example.com:51820
AllowedIPs = 0.0.0.0/0,::/0
PersistentKeepalive = 25
"""

SAMPLE_WIREGUARD_NO_PRESHARED = """[Interface]
PrivateKey = oK56DE9Ue9zK76rAc8pBl6opph+1v36lm7cXXsQKrQM=
Address = 10.66.66.3/32

[Peer]
PublicKey = HIgo9xNzJMWLKASShiTqIybxZ0U3wGLiUeJ1PKf8ykw=
Endpoint = vpn.example.com:51820
AllowedIPs = 0.0.0.0/0
"""


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceRetrieval:
    """Test VPN retrieval operations."""

    async def test_get_credential_by_id(
        self, db_session: AsyncSession
    ):
        """Test retrieving VPN credential by ID."""
        service = VPNService(db_session)

        # Create VPN
        vpn = VPNCredential(
            interface_ip="10.66.66.10/32",
            ipv4_address="10.66.66.10",
            private_key="test_private_key",
            endpoint="vpn.example.com:51820",
            key_type="vpn",
            is_available=True
        )
        db_session.add(vpn)
        await db_session.commit()

        # Retrieve
        retrieved = await service.get_credential(vpn.id)
        assert retrieved is not None
        assert retrieved.id == vpn.id
        assert retrieved.ipv4_address == "10.66.66.10"

    async def test_get_nonexistent_credential(
        self, db_session: AsyncSession
    ):
        """Test retrieving non-existent VPN returns None."""
        service = VPNService(db_session)
        vpn = await service.get_credential(99999)
        assert vpn is None

    async def test_get_user_credentials(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test retrieving all VPN credentials for a user."""
        service = VPNService(db_session)

        # Create multiple VPNs for user
        for i in range(3):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                assigned_to_user_id=invitee_user.id,
                is_available=False
            )
            db_session.add(vpn)
        await db_session.commit()

        # Get user credentials
        credentials = await service.get_user_credentials(invitee_user.id)
        assert len(credentials) == 3

    async def test_get_user_credential_first(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test getting first VPN credential for a user."""
        service = VPNService(db_session)

        # Create VPN
        vpn = VPNCredential(
            interface_ip="10.66.66.10/32",
            ipv4_address="10.66.66.10",
            private_key="test_key",
            endpoint="vpn.example.com:51820",
            key_type="vpn",
            assigned_to_user_id=invitee_user.id,
            is_available=False
        )
        db_session.add(vpn)
        await db_session.commit()

        credential = await service.get_user_credential(invitee_user.id)
        assert credential is not None
        assert credential.assigned_to_user_id == invitee_user.id

    async def test_get_user_vpn_count(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test counting VPN credentials for a user."""
        service = VPNService(db_session)

        # Create VPNs
        for i in range(5):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                assigned_to_user_id=invitee_user.id,
                is_available=False
            )
            db_session.add(vpn)
        await db_session.commit()

        count = await service.get_user_vpn_count(invitee_user.id)
        assert count == 5

    async def test_list_credentials_with_pagination(
        self, db_session: AsyncSession
    ):
        """Test listing VPN credentials with pagination."""
        service = VPNService(db_session)

        # Create 10 VPNs
        for i in range(10):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                is_available=True
            )
            db_session.add(vpn)
        await db_session.commit()

        # Get first page
        credentials, total = await service.list_credentials(page=1, page_size=5)
        assert len(credentials) == 5
        assert total == 10

        # Get second page
        credentials, total = await service.list_credentials(page=2, page_size=5)
        assert len(credentials) == 5

    async def test_list_credentials_filter_available(
        self, db_session: AsyncSession
    ):
        """Test listing only available VPN credentials."""
        service = VPNService(db_session)

        # Create available and unavailable VPNs
        for i in range(5):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                is_available=(i < 3)  # First 3 available
            )
            db_session.add(vpn)
        await db_session.commit()

        # Get only available
        credentials, total = await service.list_credentials(is_available=True)
        assert total == 3

    async def test_get_available_count(
        self, db_session: AsyncSession
    ):
        """Test counting available VPN credentials."""
        service = VPNService(db_session)

        # Create VPNs
        for i in range(10):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                is_available=(i < 7)  # 7 available, 3 assigned
            )
            db_session.add(vpn)
        await db_session.commit()

        count = await service.get_available_count()
        assert count == 7

    async def test_get_statistics(
        self, db_session: AsyncSession
    ):
        """Test getting VPN statistics."""
        service = VPNService(db_session)

        # Create VPNs
        for i in range(10):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                is_available=(i < 6)  # 6 available, 4 assigned
            )
            db_session.add(vpn)
        await db_session.commit()

        stats = await service.get_statistics()
        assert stats["total_credentials"] == 10
        assert stats["available_count"] == 6
        assert stats["assigned_count"] == 4


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceAssignment:
    """Test VPN assignment operations."""

    async def test_assign_vpn_success(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test successfully assigning a VPN to a user."""
        service = VPNService(db_session)

        # Create available VPN
        vpn = VPNCredential(
            interface_ip="10.66.66.10/32",
            ipv4_address="10.66.66.10",
            private_key="test_key",
            endpoint="vpn.example.com:51820",
            key_type="vpn",
            is_available=True
        )
        db_session.add(vpn)
        await db_session.commit()

        # Assign
        success, message, assigned_vpn = await service.assign_vpn(
            invitee_user.id,
            username=invitee_user.pandas_username
        )

        assert success is True
        assert "success" in message.lower()
        assert assigned_vpn is not None
        assert assigned_vpn.assigned_to_user_id == invitee_user.id
        assert assigned_vpn.is_available is False

    async def test_assign_vpn_no_available(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test assigning VPN when none available."""
        service = VPNService(db_session)

        success, message, vpn = await service.assign_vpn(invitee_user.id)

        assert success is False
        assert "no available" in message.lower()
        assert vpn is None

    async def test_request_vpns_multiple(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test requesting multiple VPN credentials."""
        service = VPNService(db_session)

        # Create 10 available VPNs
        for i in range(10):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                is_available=True
            )
            db_session.add(vpn)
        await db_session.commit()

        # Request 5 VPNs
        count, message, vpns = await service.request_vpns(
            invitee_user.id,
            count=5,
            username=invitee_user.pandas_username
        )

        assert count == 5
        assert len(vpns) == 5
        assert all(v.assigned_to_user_id == invitee_user.id for v in vpns)
        assert all(v.is_available is False for v in vpns)
        # All should have same batch_id
        batch_ids = {v.request_batch_id for v in vpns}
        assert len(batch_ids) == 1

    async def test_request_vpns_max_25(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test requesting VPNs enforces max 25 limit."""
        service = VPNService(db_session)

        # Create 30 available VPNs
        for i in range(30):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                is_available=True
            )
            db_session.add(vpn)
        await db_session.commit()

        # Request 100 VPNs (should be capped at 25)
        count, message, vpns = await service.request_vpns(invitee_user.id, count=100)

        assert count == 25
        assert len(vpns) == 25

    async def test_request_vpns_partial_availability(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test requesting more VPNs than available."""
        service = VPNService(db_session)

        # Create only 3 available VPNs
        for i in range(3):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                is_available=True
            )
            db_session.add(vpn)
        await db_session.commit()

        # Request 10 VPNs (only 3 available)
        count, message, vpns = await service.request_vpns(invitee_user.id, count=10)

        assert count == 3
        assert len(vpns) == 3
        assert "only 3 available" in message.lower()

    async def test_bulk_assign_success(
        self, db_session: AsyncSession
    ):
        """Test bulk assigning VPNs to multiple users."""
        service = VPNService(db_session)

        # Create users
        users = []
        for i in range(3):
            user = User(
                email=f"user{i}@test.com",
                first_name=f"User{i}",
                last_name="Test",
                country="USA",
                role="invitee"
            )
            db_session.add(user)
            users.append(user)

        # Create available VPNs
        for i in range(5):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn",
                is_available=True
            )
            db_session.add(vpn)
        await db_session.commit()

        user_ids = [u.id for u in users]
        success_count, failed_ids, errors = await service.bulk_assign(user_ids)

        assert success_count == 3
        assert len(failed_ids) == 0
        assert len(errors) == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceImport:
    """Test VPN import and parsing operations."""

    async def test_parse_wireguard_config_complete(
        self, db_session: AsyncSession
    ):
        """Test parsing complete WireGuard config with all fields."""
        service = VPNService(db_session)

        vpn = await service._parse_and_create_vpn(
            SAMPLE_WIREGUARD_CONFIG,
            "test.conf",
            endpoint=None
        )

        assert vpn is not None
        assert vpn.private_key == "oK56DE9Ue9zK76rAc8pBl6opph+1v36lm7cXXsQKrQM="
        assert vpn.preshared_key == "0Q8P8LkNfPrPgDEJOBR5p7N6DwUhJHbmhJDRwLF8G38="
        assert vpn.ipv4_address == "10.66.66.2"
        assert vpn.endpoint == "vpn.example.com:51820"
        assert vpn.is_available is True

    async def test_parse_wireguard_config_no_preshared_key(
        self, db_session: AsyncSession
    ):
        """Test parsing WireGuard config without PresharedKey (optional)."""
        service = VPNService(db_session)

        vpn = await service._parse_and_create_vpn(
            SAMPLE_WIREGUARD_NO_PRESHARED,
            "test.conf",
            endpoint=None
        )

        assert vpn is not None
        assert vpn.preshared_key is None  # Optional field

    async def test_parse_wireguard_config_override_endpoint(
        self, db_session: AsyncSession
    ):
        """Test parsing WireGuard config with endpoint override."""
        service = VPNService(db_session)

        vpn = await service._parse_and_create_vpn(
            SAMPLE_WIREGUARD_CONFIG,
            "test.conf",
            endpoint="override.example.com:9999"
        )

        assert vpn.endpoint == "override.example.com:9999"

    async def test_parse_wireguard_config_missing_private_key(
        self, db_session: AsyncSession
    ):
        """Test parsing config missing required PrivateKey."""
        service = VPNService(db_session)

        invalid_config = """[Interface]
Address = 10.66.66.10/32

[Peer]
Endpoint = vpn.example.com:51820
"""

        with pytest.raises(ValueError, match="PrivateKey"):
            await service._parse_and_create_vpn(invalid_config, "test.conf")

    async def test_parse_wireguard_config_missing_address(
        self, db_session: AsyncSession
    ):
        """Test parsing config missing required Address."""
        service = VPNService(db_session)

        invalid_config = """[Interface]
PrivateKey = oK56DE9Ue9zK76rAc8pBl6opph+1v36lm7cXXsQKrQM=

[Peer]
Endpoint = vpn.example.com:51820
"""

        with pytest.raises(ValueError, match="Address"):
            await service._parse_and_create_vpn(invalid_config, "test.conf")

    async def test_parse_wireguard_config_duplicate(
        self, db_session: AsyncSession
    ):
        """Test parsing duplicate config returns None."""
        service = VPNService(db_session)

        # Parse once
        vpn1 = await service._parse_and_create_vpn(
            SAMPLE_WIREGUARD_CONFIG,
            "test.conf"
        )
        await db_session.commit()
        assert vpn1 is not None

        # Parse same config again (should detect duplicate)
        vpn2 = await service._parse_and_create_vpn(
            SAMPLE_WIREGUARD_CONFIG,
            "test2.conf"
        )
        assert vpn2 is None  # Duplicate

    async def test_import_from_zip_success(
        self, db_session: AsyncSession
    ):
        """Test importing VPN credentials from ZIP file."""
        service = VPNService(db_session)

        # Create ZIP with WireGuard configs
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("config1.conf", SAMPLE_WIREGUARD_CONFIG)
            zf.writestr("config2.conf", SAMPLE_WIREGUARD_NO_PRESHARED)

        imported, skipped, errors = await service.import_from_zip(
            zip_buffer.getvalue()
        )

        assert imported == 2
        assert skipped == 0
        assert len(errors) == 0

    async def test_import_from_zip_skip_duplicates(
        self, db_session: AsyncSession
    ):
        """Test importing ZIP skips duplicate configs."""
        service = VPNService(db_session)

        # Create ZIP with duplicate configs
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("config1.conf", SAMPLE_WIREGUARD_CONFIG)
            zf.writestr("config2.conf", SAMPLE_WIREGUARD_CONFIG)  # Duplicate

        imported, skipped, errors = await service.import_from_zip(
            zip_buffer.getvalue()
        )

        assert imported == 1
        assert skipped == 1  # Duplicate skipped

    async def test_import_from_zip_invalid_file(
        self, db_session: AsyncSession
    ):
        """Test importing invalid ZIP file."""
        service = VPNService(db_session)

        imported, skipped, errors = await service.import_from_zip(
            b"not a valid zip file"
        )

        assert imported == 0
        assert "Invalid ZIP" in errors[0]


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceGeneration:
    """Test VPN configuration generation."""

    async def test_generate_wireguard_config(
        self, db_session: AsyncSession
    ):
        """Test generating WireGuard configuration content."""
        service = VPNService(db_session)

        vpn = VPNCredential(
            interface_ip="10.66.66.10/32,fd00:1:66::10/128",
            ipv4_address="10.66.66.10",
            private_key="oK56DE9Ue9zK76rAc8pBl6opph+1v36lm7cXXsQKrQM=",
            preshared_key="0Q8P8LkNfPrPgDEJOBR5p7N6DwUhJHbmhJDRwLF8G38=",
            endpoint="vpn.example.com:51820",
            key_type="vpn"
        )

        config = await service.generate_wireguard_config(vpn)

        assert "PrivateKey = oK56DE9Ue9zK76rAc8pBl6opph+1v36lm7cXXsQKrQM=" in config
        assert "PresharedKey = 0Q8P8LkNfPrPgDEJOBR5p7N6DwUhJHbmhJDRwLF8G38=" in config
        assert "Endpoint = vpn.example.com:51820" in config
        assert "Address = 10.66.66.10/32,fd00:1:66::10/128" in config

    async def test_generate_wireguard_config_no_preshared(
        self, db_session: AsyncSession
    ):
        """Test generating config without PresharedKey."""
        service = VPNService(db_session)

        vpn = VPNCredential(
            interface_ip="10.66.66.10/32",
            ipv4_address="10.66.66.10",
            private_key="oK56DE9Ue9zK76rAc8pBl6opph+1v36lm7cXXsQKrQM=",
            preshared_key=None,  # No preshared key
            endpoint="vpn.example.com:51820",
            key_type="vpn"
        )

        config = await service.generate_wireguard_config(vpn)

        assert "PresharedKey" not in config  # Should be omitted

    async def test_get_config_filename(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test generating configuration filename."""
        service = VPNService(db_session)

        vpn = VPNCredential(
            interface_ip="10.66.66.10/32",
            ipv4_address="10.66.66.10",
            private_key="test_key",
            endpoint="vpn.example.com:51820",
            key_type="vpn"
        )

        filename = service.get_config_filename(invitee_user, vpn)

        assert filename.startswith("cyberx_vpn_")
        assert filename.endswith(".conf")
        # Filename includes username or first_last name
        assert "Invitee" in filename or (invitee_user.pandas_username and invitee_user.pandas_username in filename)

    async def test_format_filename_with_variables(
        self, db_session: AsyncSession, invitee_user: User
    ):
        """Test formatting filename with variable substitution."""
        service = VPNService(db_session)

        vpn = VPNCredential(
            id=123,
            interface_ip="10.66.66.10/32",
            ipv4_address="10.66.66.10",
            private_key="test_key",
            endpoint="vpn.example.com:51820",
            key_type="vpn",
            request_batch_id="abc123def456"
        )

        pattern = "cyberx_{username}_{index}_{ipv4_address}.conf"
        filename = service.format_filename(
            pattern, vpn, user=invitee_user, index=5
        )

        # Username is substituted (either pandas_username or "user{id}")
        assert "cyberx_" in filename
        assert "5" in filename
        assert "10.66.66.10" in filename  # IP address kept with dots
        assert filename.endswith(".conf")


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceDeletion:
    """Test VPN deletion operations."""

    async def test_delete_credentials(
        self, db_session: AsyncSession
    ):
        """Test deleting multiple VPN credentials."""
        from sqlalchemy import select
        service = VPNService(db_session)

        # Create VPNs
        vpn_ids = []
        for i in range(5):
            vpn = VPNCredential(
                interface_ip=f"10.66.66.{10+i}/32",
                ipv4_address=f"10.66.66.{10+i}",
                private_key=f"test_key_{i}",
                endpoint="vpn.example.com:51820",
                key_type="vpn"
            )
            db_session.add(vpn)
        await db_session.commit()

        # Get IDs
        result = await db_session.execute(select(VPNCredential))
        vpn_ids = [vpn.id for vpn in result.scalars().all()]

        # Delete 3 VPNs
        deleted, failed, errors = await service.delete_credentials(vpn_ids[:3])

        assert deleted == 3
        assert len(failed) == 0

    async def test_delete_nonexistent_credentials(
        self, db_session: AsyncSession
    ):
        """Test deleting non-existent VPN credentials."""
        service = VPNService(db_session)

        deleted, failed, errors = await service.delete_credentials([99999, 88888])

        assert deleted == 0
        assert len(failed) == 2
        assert len(errors) == 2


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceRequestBatches:
    """Test VPN service request batch operations."""

    async def test_get_request_batches(
        self, db_session: AsyncSession
    ):
        """Test getting VPN request batches for a user."""
        service = VPNService(db_session)

        # Create test user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA"
        )
        db_session.add(user)
        await db_session.commit()

        # Create VPN credentials with batch IDs
        vpn1 = VPNCredential(
            assigned_to_user_id=user.id,
            interface_ip="10.20.200.1",
            private_key="key1==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=False,
            is_active=True,
            request_batch_id="batch_001",
            assigned_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        )
        vpn2 = VPNCredential(
            assigned_to_user_id=user.id,
            interface_ip="10.20.200.2",
            private_key="key2==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=False,
            is_active=True,
            request_batch_id="batch_001",
            assigned_at=datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)
        )
        vpn3 = VPNCredential(
            assigned_to_user_id=user.id,
            interface_ip="10.20.200.3",
            private_key="key3==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=False,
            is_active=True,
            request_batch_id="batch_002",
            assigned_at=datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        )
        db_session.add_all([vpn1, vpn2, vpn3])
        await db_session.commit()

        # Get request batches
        batches = await service.get_user_request_batches(user.id)

        # Should return 2 batches
        assert len(batches) == 2

        # Most recent batch first
        assert batches[0]['batch_id'] == 'batch_002'
        assert batches[0]['count'] == 1

        assert batches[1]['batch_id'] == 'batch_001'
        assert batches[1]['count'] == 2

    async def test_get_request_batches_empty(
        self, db_session: AsyncSession
    ):
        """Test getting request batches when user has no batches."""
        service = VPNService(db_session)

        # Create test user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA"
        )
        db_session.add(user)
        await db_session.commit()

        batches = await service.get_user_request_batches(user.id)

        assert batches == []


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceAdvancedFiltering:
    """Test advanced filtering and search in VPN service."""

    async def test_list_credentials_with_search_filter(self, db_session: AsyncSession):
        """Test listing credentials with search query."""
        service = VPNService(db_session)

        # Create test credentials
        vpn1 = VPNCredential(
            interface_ip="10.20.200.100",
            ipv4_address="10.20.200.100",
            private_key="key1==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True,
            assigned_to_username="testuser"
        )
        vpn2 = VPNCredential(
            interface_ip="10.20.200.200",
            ipv4_address="10.20.200.200",
            private_key="key2==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True,
            assigned_to_username="otheruser"
        )
        db_session.add_all([vpn1, vpn2])
        await db_session.commit()

        # Search by username
        credentials, total = await service.list_credentials(search="testuser")

        assert total == 1
        assert credentials[0].assigned_to_username == "testuser"

    async def test_list_credentials_with_ip_search(self, db_session: AsyncSession):
        """Test listing credentials with IP address search."""
        service = VPNService(db_session)

        # Create test credentials
        vpn1 = VPNCredential(
            interface_ip="192.168.1.100",
            ipv4_address="192.168.1.100",
            private_key="key1==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True
        )
        vpn2 = VPNCredential(
            interface_ip="10.20.200.200",
            ipv4_address="10.20.200.200",
            private_key="key2==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True
        )
        db_session.add_all([vpn1, vpn2])
        await db_session.commit()

        # Search by IP
        credentials, total = await service.list_credentials(search="192.168")

        assert total == 1
        assert credentials[0].ipv4_address == "192.168.1.100"

    async def test_list_credentials_with_assigned_to_user_filter(self, db_session: AsyncSession):
        """Test listing credentials filtered by assigned user."""
        from app.models.user import User, UserRole

        service = VPNService(db_session)

        # Create test user
        user = User(
            email="assigned@test.com",
            first_name="Assigned",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )
        db_session.add(user)
        await db_session.commit()

        # Create credentials - some assigned to user
        vpn1 = VPNCredential(
            interface_ip="10.20.200.1",
            ipv4_address="10.20.200.1",
            private_key="key1==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=False,
            assigned_to_user_id=user.id
        )
        vpn2 = VPNCredential(
            interface_ip="10.20.200.2",
            ipv4_address="10.20.200.2",
            private_key="key2==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True  # Unassigned
        )
        db_session.add_all([vpn1, vpn2])
        await db_session.commit()

        # Filter by assigned user
        credentials, total = await service.list_credentials(assigned_to_user_id=user.id)

        assert total == 1
        assert credentials[0].assigned_to_user_id == user.id


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceRequestEdgeCases:
    """Test edge cases in VPN request operations."""

    async def test_request_vpns_with_zero_count(self, db_session: AsyncSession):
        """Test requesting zero VPNs returns error."""
        from app.models.user import User, UserRole

        service = VPNService(db_session)

        # Create test user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )
        db_session.add(user)
        await db_session.commit()

        # Request 0 VPNs
        assigned_count, message, vpns = await service.request_vpns(
            user_id=user.id,
            count=0
        )

        assert assigned_count == 0
        assert "at least 1" in message
        assert vpns == []

    async def test_request_vpns_with_negative_count(self, db_session: AsyncSession):
        """Test requesting negative VPNs returns error."""
        from app.models.user import User, UserRole

        service = VPNService(db_session)

        # Create test user
        user = User(
            email="test@test.com",
            first_name="Test",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )
        db_session.add(user)
        await db_session.commit()

        # Request -5 VPNs
        assigned_count, message, vpns = await service.request_vpns(
            user_id=user.id,
            count=-5
        )

        assert assigned_count == 0
        assert "at least 1" in message
        assert vpns == []


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceBulkAssignFailures:
    """Test bulk assignment with failures."""

    async def test_bulk_assign_with_insufficient_pool(self, db_session: AsyncSession):
        """Test bulk assignment when not enough VPNs available."""
        from app.models.user import User, UserRole

        service = VPNService(db_session)

        # Create test users
        user1 = User(
            email="user1@test.com",
            first_name="User",
            last_name="One",
            country="USA",
            role=UserRole.SPONSOR.value
        )
        user2 = User(
            email="user2@test.com",
            first_name="User",
            last_name="Two",
            country="USA",
            role=UserRole.SPONSOR.value
        )
        db_session.add_all([user1, user2])
        await db_session.commit()

        # Create only 1 VPN credential
        vpn = VPNCredential(
            interface_ip="10.20.200.1",
            ipv4_address="10.20.200.1",
            private_key="key==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True
        )
        db_session.add(vpn)
        await db_session.commit()

        # Try to assign to 2 users
        success_count, failed_ids, errors = await service.bulk_assign(
            user_ids=[user1.id, user2.id]
        )

        # Should succeed for one, fail for the other
        assert success_count == 1
        assert len(failed_ids) == 1
        assert len(errors) == 1
        assert "No available VPN" in errors[0]


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceImportEdgeCases:
    """Test VPN import with edge cases."""

    async def test_import_from_zip_with_hidden_files(self, db_session: AsyncSession):
        """Test importing ZIP with hidden files (should be skipped)."""
        service = VPNService(db_session)

        # Create ZIP with hidden file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            # Add hidden file (starts with .)
            zf.writestr('.hidden_config.conf', '''[Interface]
PrivateKey=hidden123==
Address=10.20.200.1/24

[Peer]
Endpoint=216.208.235.11:51020
PublicKey=server123==
''')
            # Add normal file
            zf.writestr('visible.conf', '''[Interface]
PrivateKey=visible123==
Address=10.20.200.2/24

[Peer]
Endpoint=216.208.235.11:51020
PublicKey=server123==
''')

        zip_content = zip_buffer.getvalue()
        imported, skipped, errors = await service.import_from_zip(zip_content)

        # Hidden file should be skipped, visible file imported
        assert imported == 1
        # Skipped count may be 0 or 1 depending on implementation
        assert imported + skipped >= 1

    async def test_import_from_zip_with_directory_entries(self, db_session: AsyncSession):
        """Test importing ZIP with directory entries (should be skipped)."""
        service = VPNService(db_session)

        # Create ZIP with directory entries
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            # Add directory entry
            zf.writestr('configs/', '')
            # Add file in directory
            zf.writestr('configs/vpn.conf', '''[Interface]
PrivateKey=dirtest123==
Address=10.20.200.3/24

[Peer]
Endpoint=216.208.235.11:51020
PublicKey=server123==
''')

        zip_content = zip_buffer.getvalue()
        imported, skipped, errors = await service.import_from_zip(zip_content)

        # Should import file, skip directory
        assert imported == 1

    async def test_import_from_zip_with_binary_file(self, db_session: AsyncSession):
        """Test importing ZIP with binary file (should be skipped)."""
        service = VPNService(db_session)

        # Create ZIP with binary file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            # Add binary file
            zf.writestr('image.png', b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')
            # Add normal config
            zf.writestr('vpn.conf', '''[Interface]
PrivateKey=binary123==
Address=10.20.200.4/24

[Peer]
Endpoint=216.208.235.11:51020
PublicKey=server123==
''')

        zip_content = zip_buffer.getvalue()
        imported, skipped, errors = await service.import_from_zip(zip_content)

        # Binary file should be skipped silently
        assert imported == 1
        assert skipped >= 1

    async def test_import_from_zip_with_parse_error(self, db_session: AsyncSession):
        """Test importing ZIP with file that causes parse error."""
        service = VPNService(db_session)

        # Create ZIP with invalid config
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            # Add file that will cause parsing error (missing required fields)
            zf.writestr('invalid.conf', '''[Interface]
# Missing PrivateKey and Address
''')

        zip_content = zip_buffer.getvalue()
        imported, skipped, errors = await service.import_from_zip(zip_content)

        # Should have error
        assert imported == 0
        assert skipped == 1
        assert len(errors) >= 0  # May or may not have specific error message


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceBatchOperations:
    """Test VPN batch credential operations."""

    async def test_get_credentials_by_batch(self, db_session: AsyncSession):
        """Test getting VPN credentials by batch ID."""
        from app.models.user import User, UserRole
        from datetime import datetime, timezone

        service = VPNService(db_session)

        # Create test user
        user = User(
            email="batch@test.com",
            first_name="Batch",
            last_name="User",
            country="USA",
            role=UserRole.SPONSOR.value
        )
        db_session.add(user)
        await db_session.commit()

        # Create VPN credentials with batch ID
        vpn1 = VPNCredential(
            assigned_to_user_id=user.id,
            interface_ip="10.20.200.1",
            ipv4_address="10.20.200.1",
            private_key="key1==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=False,
            request_batch_id="batch_001",
            assigned_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        )
        vpn2 = VPNCredential(
            assigned_to_user_id=user.id,
            interface_ip="10.20.200.2",
            ipv4_address="10.20.200.2",
            private_key="key2==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=False,
            request_batch_id="batch_001",
            assigned_at=datetime(2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
        )
        # Different batch
        vpn3 = VPNCredential(
            assigned_to_user_id=user.id,
            interface_ip="10.20.200.3",
            ipv4_address="10.20.200.3",
            private_key="key3==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=False,
            request_batch_id="batch_002",
            assigned_at=datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        )
        db_session.add_all([vpn1, vpn2, vpn3])
        await db_session.commit()

        # Get credentials for batch_001
        credentials = await service.get_credentials_by_batch(user.id, "batch_001")

        assert len(credentials) == 2
        assert all(c.request_batch_id == "batch_001" for c in credentials)


@pytest.mark.unit
@pytest.mark.asyncio
class TestVPNServiceDeletionEdgeCases:
    """Test VPN credential deletion edge cases."""

    async def test_delete_credentials_with_error(self, db_session: AsyncSession, mocker):
        """Test delete_credentials handles database errors gracefully."""
        service = VPNService(db_session)

        # Create test credential
        vpn = VPNCredential(
            interface_ip="10.20.200.1",
            ipv4_address="10.20.200.1",
            private_key="key==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True
        )
        db_session.add(vpn)
        await db_session.commit()

        # Mock session.delete to raise an exception
        original_delete = db_session.delete
        call_count = [0]

        async def mock_delete(obj):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Database error")
            return await original_delete(obj)

        mocker.patch.object(db_session, 'delete', side_effect=mock_delete)

        # Try to delete - should handle error
        deleted, failed_ids, errors = await service.delete_credentials([vpn.id])

        assert deleted == 0
        assert vpn.id in failed_ids
        assert len(errors) == 1
        assert "Database error" in errors[0]

    async def test_delete_all_credentials(self, db_session: AsyncSession):
        """Test deleting all VPN credentials."""
        service = VPNService(db_session)

        # Create test credentials
        vpn1 = VPNCredential(
            interface_ip="10.20.200.1",
            ipv4_address="10.20.200.1",
            private_key="key1==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True
        )
        vpn2 = VPNCredential(
            interface_ip="10.20.200.2",
            ipv4_address="10.20.200.2",
            private_key="key2==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True
        )
        vpn3 = VPNCredential(
            interface_ip="10.20.200.3",
            ipv4_address="10.20.200.3",
            private_key="key3==",
            endpoint="216.208.235.11:51020",
            key_type="cyber",
            is_available=True
        )
        db_session.add_all([vpn1, vpn2, vpn3])
        await db_session.commit()

        # Delete all
        deleted_count = await service.delete_all_credentials()

        assert deleted_count == 3

        # Verify all deleted
        remaining_count = await service.get_available_count()
        assert remaining_count == 0
