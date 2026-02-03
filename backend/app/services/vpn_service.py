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
            .where(VPNCredential.is_available == True)
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
            .where(VPNCredential.is_available == True)
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
        """Get count of available VPN credentials."""
        result = await self.session.execute(
            select(func.count(VPNCredential.id))
            .where(VPNCredential.is_available == True)
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

    async def import_from_zip(
        self,
        zip_content: bytes,
        endpoint: Optional[str] = None
    ) -> Tuple[int, int, List[str]]:
        """
        Import VPN credentials from a ZIP file containing WireGuard configuration files.

        Validates files by content (presence of PrivateKey, Address, Endpoint)
        rather than file extension, allowing flexibility in file naming.

        Args:
            zip_content: Raw bytes of the ZIP file
            endpoint: Optional VPN server endpoint override for all imported configs
                     (if not provided, will be parsed from each config file)

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
                            config_content, filename, endpoint
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
        endpoint: Optional[str] = None
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

        Returns:
            VPNCredential object if valid, None if invalid or duplicate

        Raises:
            ValueError: If config is missing required fields
        """
        private_key = None
        preshared_key = None  # Optional
        addresses = []
        parsed_endpoint = None

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

        # Create the credential
        vpn = VPNCredential(
            interface_ip=interface_ip,
            ipv4_address=ipv4_address,
            ipv6_local=ipv6_local,
            ipv6_global=ipv6_global,
            private_key=private_key,
            preshared_key=preshared_key,
            endpoint=final_endpoint,
            key_type="vpn",  # Generic type
            file_hash=file_hash,
            is_available=True,
            is_active=True
        )

        self.session.add(vpn)
        return vpn

    def generate_wireguard_config(self, vpn: VPNCredential) -> str:
        """Generate WireGuard configuration file content."""
        # Parse interface IPs (no spaces after commas to match import format)
        interface_ips = [ip.strip() for ip in vpn.interface_ip.split(",")]
        address_line = ",".join(interface_ips)

        # Build PresharedKey line only if present (omit if None)
        preshared_line = f"PresharedKey = {vpn.preshared_key}\n" if vpn.preshared_key else ""

        # Match import format: [Peer] section first, then [Interface]
        config = f"""[Peer]
Endpoint = {vpn.endpoint}
PublicKey = {settings.VPN_SERVER_PUBLIC_KEY}
{preshared_line}AllowedIPs = {settings.VPN_ALLOWED_IPS}
PersistentKeepalive = 25
[Interface]
PrivateKey = {vpn.private_key}
Address = {address_line}
DNS = {settings.VPN_DNS_SERVERS}
"""
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
