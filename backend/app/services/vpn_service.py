"""VPN service for managing VPN credentials."""
import re
import zipfile
import io
import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.vpn import VPNCredential
from app.config import get_settings


settings = get_settings()


class VPNService:
    """Service for managing VPN credentials."""

    def __init__(self, session: AsyncSession):
        """Initialize VPN service."""
        self.session = session

    async def get_credential(self, vpn_id: int) -> Optional[VPNCredential]:
        """Get a VPN credential by ID."""
        result = await self.session.execute(
            select(VPNCredential).where(VPNCredential.id == vpn_id)
        )
        return result.scalar_one_or_none()

    async def get_user_credentials(self, user_id: int) -> List[VPNCredential]:
        """Get all VPN credentials assigned to a user."""
        result = await self.session.execute(
            select(VPNCredential)
            .where(VPNCredential.assigned_to_user_id == user_id)
            .order_by(VPNCredential.assigned_at.desc())
        )
        return list(result.scalars().all())

    async def get_user_credential(self, user_id: int) -> Optional[VPNCredential]:
        """Get first VPN credential assigned to a user (for backwards compatibility)."""
        credentials = await self.get_user_credentials(user_id)
        return credentials[0] if credentials else None

    async def get_user_vpn_count(self, user_id: int) -> int:
        """Get count of VPN credentials assigned to a user."""
        result = await self.session.execute(
            select(func.count(VPNCredential.id))
            .where(VPNCredential.assigned_to_user_id == user_id)
        )
        return result.scalar() or 0

    async def list_credentials(
        self,
        page: int = 1,
        page_size: int = 50,
        is_available: Optional[bool] = None,
        assignment_type: Optional[str] = None,
        assigned_to_user_id: Optional[int] = None,
        search: Optional[str] = None
    ) -> Tuple[List[VPNCredential], int]:
        """List VPN credentials with filtering and pagination."""
        query = select(VPNCredential)
        count_query = select(func.count(VPNCredential.id))

        # Apply filters
        if is_available is not None:
            query = query.where(VPNCredential.is_available == is_available)
            count_query = count_query.where(VPNCredential.is_available == is_available)

        if assignment_type is not None:
            query = query.where(VPNCredential.assignment_type == assignment_type)
            count_query = count_query.where(VPNCredential.assignment_type == assignment_type)

        if assigned_to_user_id is not None:
            query = query.where(VPNCredential.assigned_to_user_id == assigned_to_user_id)
            count_query = count_query.where(VPNCredential.assigned_to_user_id == assigned_to_user_id)

        if search:
            search_filter = or_(
                VPNCredential.ipv4_address.ilike(f"%{search}%"),
                VPNCredential.assigned_to_username.ilike(f"%{search}%")
            )
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        # Get total count
        total_result = await self.session.execute(count_query)
        total = total_result.scalar()

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.order_by(VPNCredential.id).offset(offset).limit(page_size)

        result = await self.session.execute(query)
        credentials = result.scalars().all()

        return list(credentials), total

    async def assign_vpn(
        self,
        user_id: int,
        username: Optional[str] = None
    ) -> Tuple[bool, str, Optional[VPNCredential]]:
        """
        Assign an available VPN credential to a user.

        Uses SELECT FOR UPDATE with skip_locked to prevent race conditions
        when multiple requests try to assign the same VPN credential.

        Returns:
            Tuple of (success, message, vpn_credential)
        """
        # Find available credential with row-level lock
        # skip_locked=True: Skip rows locked by other transactions (prevents deadlocks)
        result = await self.session.execute(
            select(VPNCredential)
            .where(
                VPNCredential.is_available == True,
                VPNCredential.assignment_type == "USER_REQUESTABLE"  # Only user-requestable VPNs
            )
            .order_by(func.random())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        vpn = result.scalar_one_or_none()

        if not vpn:
            return False, "No available VPN credentials", None

        # Assign to user (row is now locked until commit)
        vpn.assigned_to_user_id = user_id
        vpn.assigned_to_username = username
        vpn.assigned_at = datetime.now(timezone.utc)
        vpn.is_available = False

        await self.session.commit()
        await self.session.refresh(vpn)

        return True, "VPN assigned successfully", vpn

    async def request_vpns(
        self,
        user_id: int,
        count: int,
        username: Optional[str] = None
    ) -> Tuple[int, str, List[VPNCredential]]:
        """
        Request multiple VPN credentials for a user (participant self-service).

        Uses SELECT FOR UPDATE with skip_locked to prevent race conditions
        when multiple concurrent requests try to assign VPN credentials.

        Args:
            user_id: User requesting the VPNs
            count: Number of VPNs requested (max 25)
            username: Optional username to record in assignment

        Returns:
            Tuple of (assigned_count, message, list of assigned VPNs)
        """
        # Enforce max 25 per request
        if count > 25:
            count = 25

        if count < 1:
            return 0, "Count must be at least 1", []

        # Find available credentials with row-level lock
        # skip_locked=True: Skip rows locked by other transactions
        # This prevents race conditions during concurrent bulk assignments
        result = await self.session.execute(
            select(VPNCredential)
            .where(
                VPNCredential.is_available == True,
                VPNCredential.assignment_type == "USER_REQUESTABLE"  # Only user-requestable VPNs
            )
            .order_by(func.random())
            .limit(count)
            .with_for_update(skip_locked=True)
        )
        available_vpns = list(result.scalars().all())

        if not available_vpns:
            return 0, "No available VPN credentials", []

        # Generate unique batch ID for this request
        import uuid
        batch_id = str(uuid.uuid4())

        assigned_vpns = []
        now = datetime.now(timezone.utc)

        # Update all VPNs (rows are now locked until commit)
        for vpn in available_vpns:
            vpn.assigned_to_user_id = user_id
            vpn.assigned_to_username = username
            vpn.assigned_at = now
            vpn.request_batch_id = batch_id
            vpn.is_available = False
            assigned_vpns.append(vpn)

        await self.session.commit()

        if len(assigned_vpns) < count:
            return len(assigned_vpns), f"Assigned {len(assigned_vpns)} VPNs (only {len(assigned_vpns)} available)", assigned_vpns

        return len(assigned_vpns), f"Assigned {len(assigned_vpns)} VPN credentials", assigned_vpns

    async def get_available_count(self) -> int:
        """Get count of available VPN credentials for user requests."""
        result = await self.session.execute(
            select(func.count(VPNCredential.id))
            .where(
                VPNCredential.is_available == True,
                VPNCredential.assignment_type == 'USER_REQUESTABLE'
            )
        )
        return result.scalar() or 0

    async def bulk_assign(
        self,
        user_ids: List[int],
        usernames: Optional[dict] = None
    ) -> Tuple[int, List[int], List[str]]:
        """
        Bulk assign VPN credentials to multiple users (one VPN per user).

        Args:
            user_ids: List of user IDs to assign VPNs to
            usernames: Optional dict mapping user_id to username

        Returns:
            Tuple of (success_count, failed_ids, error_messages)
        """
        success_count = 0
        failed_ids = []
        errors = []
        usernames = usernames or {}

        for user_id in user_ids:
            username = usernames.get(user_id)
            success, message, _ = await self.assign_vpn(user_id, username)
            if success:
                success_count += 1
            else:
                failed_ids.append(user_id)
                errors.append(f"User {user_id}: {message}")

        return success_count, failed_ids, errors

    async def get_statistics(self) -> dict:
        """Get VPN statistics."""
        # Total count
        total_result = await self.session.execute(select(func.count(VPNCredential.id)))
        total = total_result.scalar() or 0

        # Available count
        available_result = await self.session.execute(
            select(func.count(VPNCredential.id)).where(VPNCredential.is_available == True)
        )
        available = available_result.scalar() or 0

        return {
            "total_credentials": total,
            "available_count": available,
            "assigned_count": total - available
        }

    # ─── Instance VPN Assignment Methods ────────────────────────────────────

    async def assign_vpn_to_instance(
        self,
        instance_id: int
    ) -> Tuple[bool, str, Optional[VPNCredential]]:
        """
        Assign an available INSTANCE_AUTO_ASSIGN VPN to an instance.

        Uses SELECT FOR UPDATE with skip_locked to prevent race conditions
        when multiple instances are being created concurrently.

        Args:
            instance_id: Instance ID to assign VPN to

        Returns:
            Tuple of (success, message, vpn_credential)
        """
        import logging
        logger = logging.getLogger(__name__)

        # Find available INSTANCE_AUTO_ASSIGN credential with row-level lock
        result = await self.session.execute(
            select(VPNCredential)
            .where(
                VPNCredential.is_available == True,
                VPNCredential.assignment_type == "INSTANCE_AUTO_ASSIGN"
            )
            .order_by(func.random())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        vpn = result.scalar_one_or_none()

        if not vpn:
            logger.warning("No available INSTANCE_AUTO_ASSIGN VPN credentials for instance %d", instance_id)
            return False, "No available INSTANCE_AUTO_ASSIGN VPN credentials", None

        # Assign to instance (row is now locked until commit)
        # Only set instance_id if it's a real ID (> 0)
        # For placeholder (0), we reserve the VPN without setting FK
        if instance_id > 0:
            vpn.assigned_to_instance_id = instance_id
        vpn.assigned_instance_at = datetime.now(timezone.utc)
        vpn.is_available = False

        await self.session.commit()
        await self.session.refresh(vpn)

        if instance_id > 0:
            logger.info("Assigned VPN %d to instance %d", vpn.id, instance_id)
        else:
            logger.info("Reserved VPN %d for instance (ID pending)", vpn.id)
        return True, "VPN assigned to instance successfully", vpn

    async def get_instance_vpn(self, instance_id: int) -> Optional[VPNCredential]:
        """
        Get VPN credential assigned to an instance.

        Args:
            instance_id: Instance ID to look up

        Returns:
            VPNCredential if found, None otherwise
        """
        result = await self.session.execute(
            select(VPNCredential)
            .where(VPNCredential.assigned_to_instance_id == instance_id)
        )
        return result.scalar_one_or_none()

    async def get_available_instance_vpn_count(self) -> int:
        """
        Get count of available INSTANCE_AUTO_ASSIGN VPN credentials.

        Returns:
            Number of available instance VPN credentials
        """
        result = await self.session.execute(
            select(func.count(VPNCredential.id))
            .where(
                VPNCredential.is_available == True,
                VPNCredential.assignment_type == "INSTANCE_AUTO_ASSIGN"
            )
        )
        return result.scalar() or 0

    async def update_assignment_type(
        self,
        vpn_id: int,
        assignment_type: str
    ) -> Tuple[bool, str]:
        """
        Update VPN assignment type.

        Can only change if VPN is not currently assigned to a user or instance.

        Args:
            vpn_id: VPN credential ID
            assignment_type: New type (USER_REQUESTABLE | INSTANCE_AUTO_ASSIGN | RESERVED)

        Returns:
            Tuple of (success, message)
        """
        # Validate assignment type
        valid_types = ["USER_REQUESTABLE", "INSTANCE_AUTO_ASSIGN", "RESERVED"]
        if assignment_type not in valid_types:
            return False, f"Invalid assignment type. Must be one of: {', '.join(valid_types)}"

        # Get the VPN credential
        vpn = await self.get_credential(vpn_id)
        if not vpn:
            return False, "VPN credential not found"

        # Check if VPN is currently assigned
        if not vpn.is_available:
            return False, "Cannot change assignment type while VPN is assigned to a user or instance"

        # Update assignment type
        vpn.assignment_type = assignment_type
        await self.session.commit()

        return True, f"Assignment type updated to {assignment_type}"

    async def bulk_update_assignment_type(
        self,
        vpn_ids: List[int],
        assignment_type: str
    ) -> Tuple[int, int, List[str]]:
        """
        Bulk update assignment type for multiple VPN credentials.

        Args:
            vpn_ids: List of VPN credential IDs
            assignment_type: New type for all VPNs

        Returns:
            Tuple of (success_count, skipped_count, error_messages)
        """
        success_count = 0
        skipped_count = 0
        errors = []

        for vpn_id in vpn_ids:
            success, message = await self.update_assignment_type(vpn_id, assignment_type)
            if success:
                success_count += 1
            else:
                skipped_count += 1
                errors.append(f"VPN {vpn_id}: {message}")

        return success_count, skipped_count, errors

    async def get_instance_pool_stats(self) -> dict:
        """
        Get statistics for INSTANCE_AUTO_ASSIGN VPN pool.

        Returns:
            Dict with total, available, and assigned counts
        """
        # Total INSTANCE_AUTO_ASSIGN VPNs
        total_result = await self.session.execute(
            select(func.count(VPNCredential.id))
            .where(VPNCredential.assignment_type == "INSTANCE_AUTO_ASSIGN")
        )
        total = total_result.scalar() or 0

        # Available INSTANCE_AUTO_ASSIGN VPNs
        available_result = await self.session.execute(
            select(func.count(VPNCredential.id))
            .where(
                VPNCredential.assignment_type == "INSTANCE_AUTO_ASSIGN",
                VPNCredential.is_available == True
            )
        )
        available = available_result.scalar() or 0

        return {
            "total": total,
            "available": available,
            "assigned": total - available
        }

    # ────────────────────────────────────────────────────────────────────────

    async def import_from_zip(
        self,
        zip_content: bytes,
        endpoint: Optional[str] = None,
        assignment_type: str = "USER_REQUESTABLE"
    ) -> Tuple[int, int, List[str]]:
        """
        Import VPN credentials from a ZIP file containing WireGuard configuration files.

        Validates files by content (presence of PrivateKey, Address, Endpoint)
        rather than file extension, allowing flexibility in file naming.

        Args:
            zip_content: Raw bytes of the ZIP file
            endpoint: Optional VPN server endpoint override for all imported configs
                     (if not provided, will be parsed from each config file)
            assignment_type: Type of assignment (USER_REQUESTABLE | INSTANCE_AUTO_ASSIGN | RESERVED)

        Returns:
            Tuple of (imported_count, skipped_count, error_messages)
        """
        imported_count = 0
        skipped_count = 0
        errors = []

        try:
            with zipfile.ZipFile(io.BytesIO(zip_content), 'r') as zf:
                for filename in zf.namelist():
                    # Skip directories
                    if filename.endswith('/'):
                        continue

                    # Skip hidden files and system files
                    basename = filename.split('/')[-1]
                    if basename.startswith('.') or basename.startswith('__'):
                        continue

                    try:
                        # Try to read as text
                        config_content = zf.read(filename).decode('utf-8')

                        # Validate and parse WireGuard config by content
                        vpn = await self._parse_and_create_vpn(
                            config_content, filename, endpoint, assignment_type
                        )
                        if vpn:
                            imported_count += 1
                        else:
                            # File parsed but was duplicate or invalid WireGuard config
                            skipped_count += 1
                    except UnicodeDecodeError:
                        # Binary file, skip silently
                        skipped_count += 1
                    except Exception as e:
                        errors.append(f"{filename}: {str(e)}")
                        skipped_count += 1

        except zipfile.BadZipFile:
            errors.append("Invalid ZIP file")
            return 0, 0, errors

        await self.session.commit()
        return imported_count, skipped_count, errors

    async def _parse_and_create_vpn(
        self,
        config_content: str,
        filename: str,
        endpoint: Optional[str] = None,
        assignment_type: str = "USER_REQUESTABLE"
    ) -> Optional[VPNCredential]:
        """
        Parse a WireGuard config file and create a VPN credential.

        Validates that the file contains required WireGuard fields:
        - PrivateKey (under [Interface]) - REQUIRED
        - Address (under [Interface]) - REQUIRED
        - Endpoint (under [Peer]) - REQUIRED (parsed from config or provided)
        - PresharedKey (under [Peer]) - OPTIONAL (provides post-quantum security)

        Args:
            config_content: Raw text content of the config file
            filename: Name of the file (for error reporting)
            endpoint: VPN server endpoint to use (optional, will be parsed from config if not provided)
            assignment_type: Type of assignment (USER_REQUESTABLE | INSTANCE_AUTO_ASSIGN | RESERVED)

        Returns:
            VPNCredential object if valid, None if invalid or duplicate

        Raises:
            ValueError: If config is missing required fields
        """
        # Required fields
        private_key = None
        addresses = []
        parsed_endpoint = None

        # Optional fields (preserve from original config)
        preshared_key = None
        mtu = None
        dns = None
        public_key = None
        allowed_ips = None
        persistent_keepalive = None
        table = None
        save_config = None
        fwmark = None

        # Parse the config
        for line in config_content.split('\n'):
            line = line.strip()
            if line.startswith('PrivateKey'):
                match = re.match(r'PrivateKey\s*=\s*(.+)', line)
                if match:
                    private_key = match.group(1).strip()
            elif line.startswith('PresharedKey'):
                match = re.match(r'PresharedKey\s*=\s*(.+)', line)
                if match:
                    preshared_key = match.group(1).strip()
            elif line.startswith('Address'):
                match = re.match(r'Address\s*=\s*(.+)', line)
                if match:
                    # Parse comma-separated addresses
                    addr_str = match.group(1).strip()
                    addresses = [a.strip() for a in addr_str.split(',')]
            elif line.startswith('Endpoint'):
                match = re.match(r'Endpoint\s*=\s*(.+)', line)
                if match:
                    parsed_endpoint = match.group(1).strip()
            elif line.startswith('MTU'):
                match = re.match(r'MTU\s*=\s*(.+)', line)
                if match:
                    mtu = match.group(1).strip()
            elif line.startswith('DNS'):
                match = re.match(r'DNS\s*=\s*(.+)', line)
                if match:
                    dns = match.group(1).strip()
            elif line.startswith('PublicKey'):
                match = re.match(r'PublicKey\s*=\s*(.+)', line)
                if match:
                    public_key = match.group(1).strip()
            elif line.startswith('AllowedIPs'):
                match = re.match(r'AllowedIPs\s*=\s*(.+)', line)
                if match:
                    allowed_ips = match.group(1).strip()
            elif line.startswith('PersistentKeepalive'):
                match = re.match(r'PersistentKeepalive\s*=\s*(.+)', line)
                if match:
                    persistent_keepalive = match.group(1).strip()
            elif line.startswith('Table'):
                match = re.match(r'Table\s*=\s*(.+)', line)
                if match:
                    table = match.group(1).strip()
            elif line.startswith('SaveConfig'):
                match = re.match(r'SaveConfig\s*=\s*(.+)', line)
                if match:
                    save_config = match.group(1).strip()
            elif line.startswith('FwMark'):
                match = re.match(r'FwMark\s*=\s*(.+)', line)
                if match:
                    fwmark = match.group(1).strip()

        # Use provided endpoint or parsed endpoint
        final_endpoint = endpoint or parsed_endpoint

        # Validate required fields (PresharedKey is optional)
        missing_fields = []
        if not private_key:
            missing_fields.append("PrivateKey")
        if not addresses:
            missing_fields.append("Address")
        if not final_endpoint:
            missing_fields.append("Endpoint")

        if missing_fields:
            raise ValueError(f"Invalid WireGuard config - missing required fields: {', '.join(missing_fields)}")

        # Extract IP addresses (no spaces after commas)
        interface_ip = ','.join(addresses)
        ipv4_address = None
        ipv6_local = None
        ipv6_global = None

        for addr in addresses:
            # Remove CIDR notation
            ip = addr.split('/')[0]
            if '.' in ip:  # IPv4
                ipv4_address = ip
            elif ip.startswith('fd00:') or ip.startswith('fe80:'):  # Link-local IPv6
                ipv6_local = ip
            elif ':' in ip:  # Other IPv6
                ipv6_global = ip

        # Generate file hash to detect duplicates
        file_hash = hashlib.sha256(config_content.encode()).hexdigest()

        # Check for duplicate
        existing = await self.session.execute(
            select(VPNCredential).where(VPNCredential.file_hash == file_hash)
        )
        if existing.scalar_one_or_none():
            return None  # Skip duplicate

        # Create the credential (preserve all fields from original config)
        vpn = VPNCredential(
            interface_ip=interface_ip,
            ipv4_address=ipv4_address,
            ipv6_local=ipv6_local,
            ipv6_global=ipv6_global,
            private_key=private_key,
            preshared_key=preshared_key,
            endpoint=final_endpoint,
            key_type="vpn",  # Generic type
            # Optional fields from original config (NULL if not present)
            mtu=mtu,
            dns=dns,
            public_key=public_key,
            allowed_ips=allowed_ips,
            persistent_keepalive=persistent_keepalive,
            table=table,
            save_config=save_config,
            fwmark=fwmark,
            file_hash=file_hash,
            assignment_type=assignment_type,  # Assignment type from import
            is_available=True,
            is_active=True
        )

        self.session.add(vpn)
        return vpn

    async def get_server_settings(self) -> dict:
        """
        Get VPN server settings from database, falling back to environment defaults.

        Returns:
            Dict with public_key, dns_servers, allowed_ips, and mtu
        """
        from app.models.app_setting import AppSetting

        result = await self.session.execute(
            select(AppSetting).where(
                AppSetting.key.in_([
                    'vpn_server_public_key',
                    'vpn_dns_servers',
                    'vpn_allowed_ips',
                    'vpn_mtu'
                ])
            )
        )
        settings_dict = {s.key: s.value for s in result.scalars().all()}

        return {
            'public_key': settings_dict.get('vpn_server_public_key', settings.VPN_SERVER_PUBLIC_KEY),
            'dns_servers': settings_dict.get('vpn_dns_servers', settings.VPN_DNS_SERVERS),
            'allowed_ips': settings_dict.get('vpn_allowed_ips', settings.VPN_ALLOWED_IPS),
            'mtu': settings_dict.get('vpn_mtu', '1420')
        }

    async def generate_wireguard_config(
        self,
        vpn: VPNCredential,
        public_key: str = None,
        dns_servers: str = None,
        allowed_ips: str = None,
        mtu: str = None
    ) -> str:
        """
        Generate WireGuard configuration file content.

        Args:
            vpn: VPN credential object
            public_key: Optional override for server public key (fetched from DB if None)
            dns_servers: Optional override for DNS servers (fetched from DB if None)
            allowed_ips: Optional override for allowed IPs (fetched from DB if None)
            mtu: Optional override for MTU size (fetched from DB if None)
        """
        # Fetch settings from database if not provided
        if public_key is None or dns_servers is None or allowed_ips is None or mtu is None:
            server_settings = await self.get_server_settings()
            public_key = public_key or server_settings['public_key']
            dns_servers = dns_servers or server_settings['dns_servers']
            allowed_ips = allowed_ips or server_settings['allowed_ips']
            mtu = mtu or server_settings['mtu']

        # Parse interface IPs (no spaces after commas to match import format)
        interface_ips = [ip.strip() for ip in vpn.interface_ip.split(",")]
        address_line = ",".join(interface_ips)

        # Use values from original config if present, otherwise fall back to server defaults
        # This ensures generated config matches uploaded config structure for hash verification
        final_dns = vpn.dns if vpn.dns is not None else dns_servers
        final_mtu = vpn.mtu if vpn.mtu is not None else mtu
        final_public_key = vpn.public_key if vpn.public_key is not None else public_key
        final_allowed_ips = vpn.allowed_ips if vpn.allowed_ips is not None else allowed_ips
        final_keepalive = vpn.persistent_keepalive if vpn.persistent_keepalive is not None else "25"

        # Build optional lines only if they were present in original config
        dns_line = f"DNS = {final_dns}\n" if vpn.dns is not None else ""
        mtu_line = f"MTU = {final_mtu}\n" if vpn.mtu is not None else ""
        table_line = f"Table = {vpn.table}\n" if vpn.table is not None else ""
        save_config_line = f"SaveConfig = {vpn.save_config}\n" if vpn.save_config is not None else ""
        fwmark_line = f"FwMark = {vpn.fwmark}\n" if vpn.fwmark is not None else ""
        preshared_line = f"PresharedKey = {vpn.preshared_key}\n" if vpn.preshared_key else ""
        allowed_ips_line = f"AllowedIPs = {final_allowed_ips}\n" if vpn.allowed_ips is not None else ""
        keepalive_line = f"PersistentKeepalive = {final_keepalive}\n" if vpn.persistent_keepalive is not None else ""

        # Standard WireGuard format: [Interface] section first, then [Peer]
        config = f"""[Interface]
PrivateKey = {vpn.private_key}
Address = {address_line}
{dns_line}{mtu_line}{table_line}{save_config_line}{fwmark_line}
[Peer]
PublicKey = {final_public_key}
{preshared_line}Endpoint = {vpn.endpoint}
{allowed_ips_line}{keepalive_line}"""
        return config

    def get_config_filename(self, user: User, vpn: VPNCredential) -> str:
        """Generate configuration filename."""
        username = user.pandas_username or f"{user.first_name}_{user.last_name}"
        username = "".join(c for c in username if c.isalnum() or c in "._-")
        return f"cyberx_{vpn.key_type}_{username}.conf"

    def format_filename(
        self,
        pattern: str,
        vpn: VPNCredential,
        user: Optional[User] = None,
        index: Optional[int] = None
    ) -> str:
        """
        Generate filename from a pattern with variable substitution.

        Available variables:
        - {username} - User's pandas_username
        - {user_id} - User ID
        - {ipv4_address} - VPN IPv4 address
        - {endpoint} - VPN endpoint
        - {index} - Sequential number
        - {id} - VPN credential ID
        - {batch_id} - Request batch ID (first 8 chars)

        Args:
            pattern: Naming pattern with variables (e.g., "cyberx_{username}_{index}.conf")
            vpn: VPN credential object
            user: Optional user object (required for username/user_id variables)
            index: Optional sequential index

        Returns:
            Formatted filename
        """
        # Build replacement dictionary
        replacements = {
            'id': str(vpn.id),
            'ipv4_address': vpn.ipv4_address or 'unknown',
            'endpoint': vpn.endpoint.replace(':', '_') if vpn.endpoint else 'unknown',
            'batch_id': vpn.request_batch_id[:8] if vpn.request_batch_id else 'unknown',
        }

        if user:
            replacements['username'] = user.pandas_username or f"user{user.id}"
            replacements['user_id'] = str(user.id)
        else:
            replacements['username'] = 'unknown'
            replacements['user_id'] = 'unknown'

        if index is not None:
            replacements['index'] = str(index)
        else:
            replacements['index'] = '1'

        # Perform replacements
        filename = pattern
        for key, value in replacements.items():
            filename = filename.replace(f'{{{key}}}', value)

        # Sanitize filename (remove/replace invalid characters)
        filename = "".join(c if c.isalnum() or c in "._-{}" else "_" for c in filename)

        # Ensure .conf extension
        if not filename.endswith('.conf'):
            filename += '.conf'

        return filename

    async def get_user_request_batches(self, user_id: int) -> List[dict]:
        """
        Get list of VPN request batches for a user.

        Returns:
            List of dicts with batch_id, requested_at, and count
        """
        from sqlalchemy import distinct

        # Get distinct batch IDs with their timestamps and counts
        result = await self.session.execute(
            select(
                VPNCredential.request_batch_id,
                func.min(VPNCredential.assigned_at).label('requested_at'),
                func.count(VPNCredential.id).label('count')
            )
            .where(
                VPNCredential.assigned_to_user_id == user_id,
                VPNCredential.request_batch_id.isnot(None)
            )
            .group_by(VPNCredential.request_batch_id)
            .order_by(func.min(VPNCredential.assigned_at).desc())
        )

        batches = []
        for row in result.all():
            batches.append({
                'batch_id': row.request_batch_id,
                'requested_at': row.requested_at,
                'count': row.count
            })

        return batches

    async def get_credentials_by_batch(self, user_id: int, batch_id: str) -> List[VPNCredential]:
        """
        Get all VPN credentials for a specific request batch.

        Args:
            user_id: User ID (for security check)
            batch_id: Request batch ID

        Returns:
            List of VPN credentials in this batch
        """
        result = await self.session.execute(
            select(VPNCredential)
            .where(
                VPNCredential.assigned_to_user_id == user_id,
                VPNCredential.request_batch_id == batch_id
            )
            .order_by(VPNCredential.assigned_at)
        )
        return list(result.scalars().all())

    async def delete_credentials(self, vpn_ids: List[int]) -> Tuple[int, List[int], List[str]]:
        """
        Delete multiple VPN credentials by ID.

        Args:
            vpn_ids: List of VPN credential IDs to delete

        Returns:
            Tuple of (deleted_count, failed_ids, error_messages)
        """
        deleted_count = 0
        failed_ids = []
        errors = []

        for vpn_id in vpn_ids:
            try:
                # Get the credential
                result = await self.session.execute(
                    select(VPNCredential).where(VPNCredential.id == vpn_id)
                )
                vpn = result.scalar_one_or_none()

                if not vpn:
                    failed_ids.append(vpn_id)
                    errors.append(f"VPN {vpn_id}: Not found")
                    continue

                # Delete the credential
                await self.session.delete(vpn)
                deleted_count += 1

            except Exception as e:
                failed_ids.append(vpn_id)
                errors.append(f"VPN {vpn_id}: {str(e)}")

        # Commit all deletes
        await self.session.commit()

        return deleted_count, failed_ids, errors

    async def delete_all_credentials(self) -> int:
        """
        Delete all VPN credentials.

        Returns:
            Number of credentials deleted
        """
        # Get all credential IDs
        result = await self.session.execute(select(VPNCredential.id))
        vpn_ids = [row[0] for row in result.all()]

        # Delete all
        deleted_count, _, _ = await self.delete_credentials(vpn_ids)

        return deleted_count
