"""Unified instance management service supporting multiple cloud providers."""
import logging
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.instance import Instance
from app.models.vpn import VPNCredential
from app.services.cloud_provider_factory import CloudProviderFactory

logger = logging.getLogger(__name__)


class InstanceService:
    """Provider-agnostic instance management service."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    async def create_and_track_instance(
        self,
        name: str,
        provider: str = "openstack",
        size: str | None = None,
        image: str | None = None,
        region: str | None = None,
        network: str | None = None,
        key_name: str | None = None,
        template_id: int | None = None,
        license_product_id: int | None = None,
        event_id: int | None = None,
        assigned_to_user_id: int | None = None,
        created_by_user_id: int | None = None,
        user_data: str | None = None,
        ssh_public_key: str | None = None,
    ) -> Instance:
        """Create instance on any cloud provider and track in DB.

        This method handles:
        - Provider selection via factory
        - Cloud-init template rendering
        - VPN assignment (if event has vpn_available=True)
        - License token generation
        - SSH key injection
        - Instance creation on provider
        - Database tracking

        Args:
            name: Instance name
            provider: Cloud provider ('openstack' or 'digitalocean')
            size: Instance size/flavor
            image: Image ID or slug
            region: Region (for DigitalOcean)
            network: Network ID (for OpenStack)
            key_name: SSH key name or ID
            template_id: Cloud-init template ID
            license_product_id: License product ID
            event_id: Event ID
            assigned_to_user_id: User ID to assign instance to
            created_by_user_id: User ID who created instance
            user_data: Raw cloud-init user data (overrides template)
            ssh_public_key: Individual SSH public key

        Returns:
            Created Instance object

        Raises:
            ValueError: If provider is unknown or required fields missing
        """
        # Get provider service
        provider_service = CloudProviderFactory.get_provider(provider, self.session)

        # Apply provider-specific defaults
        if provider == "openstack":
            size = size or self.settings.OS_DEFAULT_FLAVOR_ID
            image = image or self.settings.OS_DEFAULT_IMAGE_ID
            network = network or self.settings.OS_DEFAULT_NETWORK_ID
            key_name = key_name or self.settings.OS_DEFAULT_KEY_NAME or None

            if not all([size, image, network]):
                raise ValueError(
                    "OpenStack requires size, image, and network"
                )

        elif provider == "digitalocean":
            size = size or self.settings.DO_DEFAULT_SIZE
            image = image or self.settings.DO_DEFAULT_IMAGE
            region = region or self.settings.DO_DEFAULT_REGION

            if not all([size, image, region]):
                raise ValueError(
                    "DigitalOcean requires size, image, and region"
                )

        # Render cloud-init template if provided
        if template_id and not user_data:
            user_data = await self._render_cloud_init_template(
                template_id=template_id,
                name=name,
                license_product_id=license_product_id,
                event_id=event_id,
                ssh_public_key=ssh_public_key,
            )

        # VPN assignment (event-based)
        vpn_token_hash = None
        vpn_token_expires_at = None
        vpn_ip = None
        assigned_vpn_id = None

        if event_id:
            vpn_data = await self._assign_vpn_if_enabled(
                event_id=event_id,
                name=name,
                template_id=template_id,
                user_data=user_data,
            )

            if vpn_data:
                vpn_token_hash = vpn_data["token_hash"]
                vpn_token_expires_at = vpn_data["expires_at"]
                vpn_ip = vpn_data["ip"]
                assigned_vpn_id = vpn_data["vpn_id"]
                user_data = vpn_data["user_data"]  # Re-rendered with VPN vars

        # Create on provider
        instance_data = await provider_service.create_instance(
            name=name,
            size=size,
            image=image,
            region=region,
            network=network,
            key_name=key_name,
            user_data=user_data,
        )

        # Extract IP address and status
        ip_address = None
        status = "ERROR"
        provider_instance_id = None

        if instance_data:
            provider_instance_id = str(instance_data["id"])
            status = provider_service.normalize_status(
                instance_data.get("status", "")
            )
            ip_address = provider_service.extract_ip_address(instance_data)

        # Track in DB
        instance = Instance(
            name=name,
            provider=provider,
            provider_instance_id=provider_instance_id,
            status=status,
            ip_address=ip_address,
            # Provider-specific fields
            flavor_id=size if provider == "openstack" else None,
            network_id=network if provider == "openstack" else None,
            provider_size_slug=size if provider == "digitalocean" else None,
            provider_region=region if provider == "digitalocean" else None,
            # Common fields
            image_id=image,
            key_name=key_name,
            cloud_init_template_id=template_id,
            license_product_id=license_product_id,
            event_id=event_id,
            assigned_to_user_id=assigned_to_user_id,
            created_by_user_id=created_by_user_id,
            error_message=None if instance_data else f"Failed to create on {provider}",
            # VPN fields
            vpn_ip=vpn_ip,
            vpn_config_token=vpn_token_hash,
            vpn_config_token_expires_at=vpn_token_expires_at,
        )
        self.session.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)

        # Update VPN assignment with actual instance_id
        if assigned_vpn_id:
            await self._update_vpn_instance_assignment(assigned_vpn_id, instance.id)

        logger.info(
            "Created instance %s on %s (provider_id=%s, db_id=%d)",
            name,
            provider,
            provider_instance_id,
            instance.id
        )

        return instance

    async def _render_cloud_init_template(
        self,
        template_id: int,
        name: str,
        license_product_id: int | None,
        event_id: int | None,
        ssh_public_key: str | None,
    ) -> str:
        """Render cloud-init template with variables.

        Extracts logic from OpenStackService for reuse across providers.
        """
        from app.services.cloud_init_service import CloudInitService
        from app.services.license_service import LicenseService
        from app.models.event import Event

        cloud_init_svc = CloudInitService(self.session)
        template = await cloud_init_svc.get_template(template_id)

        if not template:
            logger.warning("Template %d not found", template_id)
            return ""

        # Prepare template variables
        variables = {
            "hostname": name,
            "instance_name": name,
        }

        # Add license variables (if license product is specified)
        if license_product_id:
            license_svc = LicenseService(self.session)
            license_token = await license_svc.generate_token(
                product_id=license_product_id,
                instance_id=None  # Will be linked after instance creation
            )

            variables["license_server"] = f"{self.settings.FRONTEND_URL}/api/license"
            variables["license_token"] = license_token
            logger.info(
                "Generated license token for product %d for instance %s",
                license_product_id,
                name
            )

        if self.settings.DOWNLOAD_BASE_URL:
            variables["download_base_url"] = self.settings.DOWNLOAD_BASE_URL

        # Add VPN variables (if configured)
        if self.settings.VPN_SERVER_PUBLIC_KEY:
            variables["vpn_server_public_key"] = self.settings.VPN_SERVER_PUBLIC_KEY
        if self.settings.VPN_SERVER_ENDPOINT:
            variables["vpn_server_endpoint"] = self.settings.VPN_SERVER_ENDPOINT
        if self.settings.VPN_DNS_SERVERS:
            variables["vpn_dns_servers"] = self.settings.VPN_DNS_SERVERS
        if self.settings.VPN_ALLOWED_IPS:
            variables["vpn_allowed_ips"] = self.settings.VPN_ALLOWED_IPS

        # Collect all available SSH keys (both individual and event keys)
        ssh_keys = []

        if ssh_public_key:
            ssh_keys.append(ssh_public_key)
            logger.info("Using individual SSH key for instance %s", name)

        if event_id:
            result = await self.session.execute(
                select(Event).where(Event.id == event_id)
            )
            event = result.scalar_one_or_none()
            if event:
                if event.is_active and event.ssh_public_key:
                    if event.ssh_public_key not in ssh_keys:
                        ssh_keys.append(event.ssh_public_key)
                        logger.info("Added event %d SSH key to instance %s", event_id, name)

        # Format SSH keys for cloud-init template
        if ssh_keys:
            if len(ssh_keys) == 1:
                variables["ssh_public_key"] = ssh_keys[0]
            else:
                # Multiple keys: first replaces placeholder, rest as list items
                variables["ssh_public_key"] = ssh_keys[0] + "\n  - " + "\n  - ".join(ssh_keys[1:])
            logger.info(
                "Added %d SSH key(s) to cloud-init template for instance %s",
                len(ssh_keys),
                name
            )

        # Render template
        user_data = cloud_init_svc.render_template(template.content, variables)
        logger.info("Rendered cloud-init template %d for instance %s", template_id, name)

        return user_data

    async def _assign_vpn_if_enabled(
        self,
        event_id: int,
        name: str,
        template_id: int | None,
        user_data: str | None,
    ) -> Optional[dict]:
        """Assign VPN to instance if event has VPN enabled.

        Returns dict with VPN data or None if VPN not assigned.
        """
        from app.models.event import Event
        from app.services.vpn_service import VPNService
        from app.services.cloud_init_service import CloudInitService

        # Fetch event to check vpn_available flag
        event_result = await self.session.execute(
            select(Event).where(Event.id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event or not event.vpn_available:
            return None

        logger.info("Event %d has VPN enabled, assigning VPN to instance %s", event_id, name)

        vpn_svc = VPNService(self.session)

        # Temporarily assign VPN with placeholder instance_id
        success, message, vpn = await vpn_svc.assign_vpn_to_instance(instance_id=0)

        if not success or not vpn:
            logger.warning("Failed to assign VPN to instance %s: %s", name, message)
            return None

        # Generate single-use token for cloud-init
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)

        logger.info(
            "Generated VPN token for instance %s, VPN ID: %d, IP: %s",
            name,
            vpn.id,
            vpn.ipv4_address
        )

        # Add VPN variables to cloud-init template and re-render
        if template_id and user_data:
            cloud_init_svc = CloudInitService(self.session)
            template = await cloud_init_svc.get_template(template_id)

            if template:
                # Re-parse original template with VPN variables
                # This is a simplified approach - in production you'd want to
                # preserve all variables from the first render
                variables = {
                    "hostname": name,
                    "instance_name": name,
                    "vpn_config_token": raw_token,
                    "vpn_config_endpoint": f"{self.settings.FRONTEND_URL}/api/cloud-init/vpn-config",
                }
                user_data = cloud_init_svc.render_template(template.content, variables)
                logger.info("Re-rendered cloud-init template with VPN variables for instance %s", name)

        return {
            "token_hash": token_hash,
            "expires_at": expires_at,
            "ip": vpn.ipv4_address,
            "vpn_id": vpn.id,
            "user_data": user_data,
        }

    async def _update_vpn_instance_assignment(
        self,
        vpn_id: int,
        instance_id: int
    ) -> None:
        """Update VPN record with actual instance_id after instance creation."""
        vpn_result = await self.session.execute(
            select(VPNCredential).where(VPNCredential.id == vpn_id)
        )
        vpn = vpn_result.scalar_one_or_none()
        if vpn:
            vpn.assigned_to_instance_id = instance_id
            await self.session.commit()
            logger.info("Updated VPN %d with instance ID %d", vpn_id, instance_id)

    async def list_tracked_instances(
        self,
        page: int = 1,
        page_size: int = 50,
        event_id: int | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Instance], int]:
        """List tracked instances with filtering and pagination (all providers)."""
        from sqlalchemy.orm import selectinload

        conditions = [Instance.deleted_at.is_(None)]

        if event_id is not None:
            conditions.append(Instance.event_id == event_id)
        if status:
            conditions.append(Instance.status == status)
        if search:
            conditions.append(
                or_(
                    Instance.name.ilike(f"%{search}%"),
                    Instance.ip_address.ilike(f"%{search}%"),
                    Instance.provider_instance_id.ilike(f"%{search}%"),
                )
            )

        # Count
        count_q = select(func.count(Instance.id)).where(*conditions)
        total = (await self.session.execute(count_q)).scalar() or 0

        # Fetch with relationships
        offset = (page - 1) * page_size
        q = (
            select(Instance)
            .options(
                selectinload(Instance.event),
                selectinload(Instance.created_by),
            )
            .where(*conditions)
            .order_by(Instance.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self.session.execute(q)
        instances = list(result.scalars().all())

        return instances, total

    async def get_tracked_instance(self, instance_id: int) -> Optional[Instance]:
        """Get a single tracked instance by ID."""
        result = await self.session.execute(
            select(Instance).where(Instance.id == instance_id)
        )
        return result.scalar_one_or_none()

    async def sync_instance_status(self, instance_id: int) -> Optional[Instance]:
        """Refresh an instance's status from its cloud provider."""
        instance = await self.get_tracked_instance(instance_id)
        if not instance or not instance.provider_instance_id:
            return instance

        try:
            # Get appropriate provider service
            provider_service = CloudProviderFactory.get_provider(
                instance.provider, self.session
            )

            # Get status from provider
            provider_data = await provider_service.get_instance_status(
                instance.provider_instance_id
            )

            if provider_data:
                # Update status
                new_status = provider_service.normalize_status(
                    provider_data.get("status", "")
                )
                instance.status = new_status

                # Update IP if available
                ip_address = provider_service.extract_ip_address(provider_data)
                if ip_address:
                    instance.ip_address = ip_address

                await self.session.commit()
                await self.session.refresh(instance)

                logger.info(
                    "Synced instance %d (%s) from %s - status: %s",
                    instance.id, instance.name, instance.provider, new_status
                )

        except Exception as e:
            logger.error(
                "Failed to sync instance %d (%s, provider=%s): %s",
                instance.id, instance.name, instance.provider, e
            )

        return instance
