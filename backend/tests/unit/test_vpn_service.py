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

        config = service.generate_wireguard_config(vpn)

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

        config = service.generate_wireguard_config(vpn)

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
