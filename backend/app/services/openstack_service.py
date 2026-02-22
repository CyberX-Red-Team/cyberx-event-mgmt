"""OpenStack instance management service.

Async port of openstack-dev/create_instance.py OpenStackClient,
using httpx instead of requests and backed by PostgreSQL for instance tracking.
"""
import base64
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.instance import Instance

logger = logging.getLogger(__name__)


class OpenStackService:
    """Async OpenStack client + DB-backed instance tracking."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()
        self._token: Optional[str] = None
        self._project_id: Optional[str] = None
        self._nova_url: Optional[str] = None
        self._neutron_url: Optional[str] = None
        self._glance_url: Optional[str] = None

    def _check_configured(self):
        """Raise if OpenStack is not configured."""
        if not self.settings.OS_AUTH_URL:
            raise ValueError(
                "OpenStack is not configured. Set OS_AUTH_URL and authentication credentials."
            )

    # ── OpenStack API Methods ───────────────────────────────────

    async def authenticate(self) -> bool:
        """Authenticate with Keystone and discover service endpoints."""
        self._check_configured()

        auth_url = self._ensure_versioned_url(self.settings.OS_AUTH_URL, "identity")

        # Build auth payload
        if self.settings.OS_APPLICATION_CREDENTIAL_ID and self.settings.OS_APPLICATION_CREDENTIAL_SECRET:
            auth_data = {
                "auth": {
                    "identity": {
                        "methods": ["application_credential"],
                        "application_credential": {
                            "id": self.settings.OS_APPLICATION_CREDENTIAL_ID,
                            "secret": self.settings.OS_APPLICATION_CREDENTIAL_SECRET,
                        },
                    }
                }
            }
        elif self.settings.OS_USERNAME and self.settings.OS_PASSWORD:
            auth_data = {
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "name": self.settings.OS_USERNAME,
                                "domain": {"name": self.settings.OS_USER_DOMAIN_NAME},
                                "password": self.settings.OS_PASSWORD,
                            }
                        },
                    },
                    "scope": {
                        "project": {
                            "name": self.settings.OS_PROJECT_NAME,
                            "domain": {"name": self.settings.OS_PROJECT_DOMAIN_NAME},
                        }
                    },
                }
            }
        else:
            raise ValueError(
                "No OpenStack credentials configured. Set app credentials or username/password."
            )

        async with httpx.AsyncClient(verify=True, timeout=30) as client:
            resp = await client.post(
                f"{auth_url}/auth/tokens",
                json=auth_data,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()

        self._token = resp.headers.get("X-Subject-Token")
        token_data = resp.json()["token"]

        if "project" in token_data:
            self._project_id = token_data["project"]["id"]

        # Discover endpoints from catalog
        catalog = token_data.get("catalog", [])
        self._discover_endpoints(catalog)

        logger.info("OpenStack authentication successful (project=%s)", self._project_id)
        return True

    def _discover_endpoints(self, catalog: list):
        """Extract Nova/Neutron/Glance endpoints from service catalog."""
        # Use configured URLs if provided, otherwise discover
        if not self.settings.OS_NOVA_URL:
            for svc in catalog:
                if svc["type"] == "compute":
                    for ep in svc["endpoints"]:
                        if ep["interface"] == "public":
                            self._nova_url = ep["url"]
                            break
                    break
        else:
            self._nova_url = self.settings.OS_NOVA_URL

        if not self.settings.OS_NEUTRON_URL:
            for svc in catalog:
                if svc["type"] == "network":
                    for ep in svc["endpoints"]:
                        if ep["interface"] == "public":
                            self._neutron_url = ep["url"]
                            break
                    break
        else:
            self._neutron_url = self.settings.OS_NEUTRON_URL

        if not self.settings.OS_GLANCE_URL:
            for svc in catalog:
                if svc["type"] == "image":
                    for ep in svc["endpoints"]:
                        if ep["interface"] == "public":
                            self._glance_url = ep["url"]
                            break
                    break
        else:
            self._glance_url = self.settings.OS_GLANCE_URL

        # Ensure versioned URLs and inject project ID for Nova
        if self._nova_url:
            self._nova_url = self._ensure_versioned_url(self._nova_url, "compute")
            if self._project_id and self._project_id not in self._nova_url:
                self._nova_url = f"{self._nova_url.rstrip('/')}/{self._project_id}"
        if self._neutron_url:
            self._neutron_url = self._ensure_versioned_url(self._neutron_url, "network")
        if self._glance_url:
            self._glance_url = self._ensure_versioned_url(self._glance_url, "image")

    def _ensure_versioned_url(self, url: str, service_type: str) -> str:
        """Ensure URL includes API version path."""
        if "/v2" in url or "/v3" in url:
            return url

        default_paths = {
            "identity": "/v3",
            "compute": "/v2.1",
            "network": "/v2.0",
            "image": "/v2",
        }
        return url.rstrip("/") + default_paths.get(service_type, "")

    def _headers(self) -> dict:
        return {"X-Auth-Token": self._token, "Content-Type": "application/json"}

    async def _ensure_authenticated(self):
        """Re-authenticate if we don't have a token."""
        if not self._token:
            await self.authenticate()

    async def create_instance_on_openstack(
        self,
        name: str,
        flavor_id: str,
        image_id: str,
        network_id: str,
        key_name: str | None = None,
        user_data: str | None = None,
    ) -> Optional[dict]:
        """Create a VM via Nova API. Returns server dict or None."""
        await self._ensure_authenticated()

        server_data: dict = {
            "server": {
                "name": name,
                "flavorRef": flavor_id,
                "imageRef": image_id,
                "networks": [{"uuid": network_id}],
            }
        }

        if key_name:
            server_data["server"]["key_name"] = key_name

        if user_data:
            encoded = base64.b64encode(user_data.encode("utf-8")).decode("utf-8")
            if len(encoded) > 65535:
                raise ValueError(
                    f"Encoded user_data is {len(encoded)} bytes, exceeds Nova's 65535-byte limit"
                )
            server_data["server"]["user_data"] = encoded

        async with httpx.AsyncClient(verify=True, timeout=60) as client:
            resp = await client.post(
                f"{self._nova_url}/servers",
                json=server_data,
                headers=self._headers(),
            )
            resp.raise_for_status()

        data = resp.json()
        if "server" not in data:
            logger.error("Unexpected Nova response: %s", data)
            return None

        logger.info("Nova instance created: %s (id=%s)", name, data["server"]["id"])
        return data["server"]

    async def delete_instance_on_openstack(self, openstack_id: str) -> bool:
        """Delete a VM via Nova API."""
        await self._ensure_authenticated()

        async with httpx.AsyncClient(verify=True, timeout=30) as client:
            resp = await client.delete(
                f"{self._nova_url}/servers/{openstack_id}",
                headers=self._headers(),
            )

        if resp.status_code in (204, 404):
            logger.info("Nova instance deleted: %s", openstack_id)
            return True

        logger.error("Failed to delete Nova instance %s: %d", openstack_id, resp.status_code)
        return False

    async def get_instance_status_from_openstack(self, openstack_id: str) -> Optional[dict]:
        """Get server details from Nova API."""
        await self._ensure_authenticated()

        async with httpx.AsyncClient(verify=True, timeout=15) as client:
            resp = await client.get(
                f"{self._nova_url}/servers/{openstack_id}",
                headers=self._headers(),
            )

        if resp.status_code == 404:
            return None

        resp.raise_for_status()
        return resp.json().get("server")

    async def list_flavors(self) -> list[dict]:
        """List available Nova flavors."""
        await self._ensure_authenticated()

        async with httpx.AsyncClient(verify=True, timeout=15) as client:
            resp = await client.get(
                f"{self._nova_url}/flavors/detail",
                headers=self._headers(),
            )
            resp.raise_for_status()

        return resp.json().get("flavors", [])

    async def list_images(self) -> list[dict]:
        """List available Glance images."""
        await self._ensure_authenticated()

        url = f"{self._glance_url}/images" if self._glance_url else f"{self._nova_url}/images/detail"

        async with httpx.AsyncClient(verify=True, timeout=15) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()

        return resp.json().get("images", [])

    async def list_networks(self) -> list[dict]:
        """List available Neutron networks."""
        await self._ensure_authenticated()

        if not self._neutron_url:
            return []

        async with httpx.AsyncClient(verify=True, timeout=15) as client:
            resp = await client.get(
                f"{self._neutron_url}/networks",
                headers=self._headers(),
            )
            resp.raise_for_status()

        return resp.json().get("networks", [])

    # ── DB-backed Instance CRUD ─────────────────────────────────

    async def create_and_track_instance(
        self,
        name: str,
        flavor_id: str | None = None,
        image_id: str | None = None,
        network_id: str | None = None,
        key_name: str | None = None,
        template_id: int | None = None,
        license_product_id: int | None = None,
        event_id: int | None = None,
        assigned_to_user_id: int | None = None,
        created_by_user_id: int | None = None,
        user_data: str | None = None,
        ssh_public_key: str | None = None,
    ) -> Instance:
        """Create an OpenStack instance and track it in the DB."""
        # Fall back to defaults
        flavor_id = flavor_id or self.settings.OS_DEFAULT_FLAVOR_ID
        image_id = image_id or self.settings.OS_DEFAULT_IMAGE_ID
        network_id = network_id or self.settings.OS_DEFAULT_NETWORK_ID
        key_name = key_name or self.settings.OS_DEFAULT_KEY_NAME or None

        if not all([flavor_id, image_id, network_id]):
            raise ValueError("flavor_id, image_id, and network_id are required")

        # Render cloud-init template if provided
        if template_id and not user_data:
            from app.services.cloud_init_service import CloudInitService
            from app.services.license_service import LicenseService
            from app.services.download_service import DownloadService
            from app.models.event import Event

            cloud_init_svc = CloudInitService(self.session)
            template = await cloud_init_svc.get_template(template_id)

            if template:
                # Prepare template variables (available for all templates)
                variables = {
                    "hostname": name,
                    "instance_name": name,
                }

                # Add license variables (if license product is specified)
                if license_product_id:
                    license_svc = LicenseService(self.session)

                    # Generate a single-use token for this instance
                    # Note: instance_id is None here since we haven't created the record yet
                    # The token will be linked to the instance after creation if needed
                    license_token = await license_svc.generate_token(
                        product_id=license_product_id,
                        instance_id=None  # Will be linked after instance creation
                    )

                    # Use integrated license server (FRONTEND_URL/api/license)
                    variables["license_server"] = f"{self.settings.FRONTEND_URL}/api/license"
                    variables["license_token"] = license_token
                    logger.info("Generated license token for product %d for instance %s", license_product_id, name)
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

                # 1. Add individual SSH key if provided
                if ssh_public_key:
                    ssh_keys.append(ssh_public_key)
                    logger.info("Using individual SSH key for instance %s", name)

                # 2. Add event SSH key if available (and not duplicate)
                if event_id:
                    result = await self.session.execute(
                        select(Event).where(Event.id == event_id)
                    )
                    event = result.scalar_one_or_none()
                    if event:
                        logger.info("Event %d found: is_active=%s, has_ssh_key=%s",
                                    event_id, event.is_active, bool(event.ssh_public_key))
                        # Only add SSH key if event is active and has a key configured
                        if event.is_active and event.ssh_public_key:
                            # Only add if it's different from individual key
                            if event.ssh_public_key not in ssh_keys:
                                ssh_keys.append(event.ssh_public_key)
                                logger.info("Added event %d SSH key to instance %s", event_id, name)
                            else:
                                logger.info("Event %d SSH key already in list (duplicate), skipping", event_id)
                        elif not event.is_active:
                            logger.warning("Event %d is inactive, not adding SSH key to instance %s", event_id, name)
                        elif not event.ssh_public_key:
                            logger.warning("Event %d has no SSH key configured", event_id)
                    else:
                        logger.warning("Event %d not found", event_id)

                # Format SSH keys for cloud-init template
                if ssh_keys:
                    # For templates with "  - {{ssh_public_key}}", support multiple keys
                    # by joining them with newline and proper indentation
                    if len(ssh_keys) == 1:
                        variables["ssh_public_key"] = ssh_keys[0]
                    else:
                        # Multiple keys: first key replaces placeholder, rest added as new list items
                        # Template: "  - {{ssh_public_key}}" becomes "  - key1\n  - key2"
                        variables["ssh_public_key"] = ssh_keys[0] + "\n  - " + "\n  - ".join(ssh_keys[1:])
                    logger.info("Added %d SSH key(s) to cloud-init template for instance %s", len(ssh_keys), name)
                else:
                    # No SSH keys available - don't add variable
                    # Cleanup logic in render_template will remove ssh_authorized_keys section
                    logger.info("No SSH keys available for instance %s - ssh_authorized_keys section will be removed", name)

                # Render template
                user_data = cloud_init_svc.render_template(template.content, variables)
                logger.info("Rendered cloud-init template %d for instance %s", template_id, name)

        # Create on OpenStack
        server = await self.create_instance_on_openstack(
            name=name,
            flavor_id=flavor_id,
            image_id=image_id,
            network_id=network_id,
            key_name=key_name,
            user_data=user_data,
        )

        # Track in DB
        instance = Instance(
            name=name,
            openstack_id=server["id"] if server else None,
            status="BUILDING" if server else "ERROR",
            flavor_id=flavor_id,
            image_id=image_id,
            network_id=network_id,
            key_name=key_name,
            cloud_init_template_id=template_id,
            license_product_id=license_product_id,
            event_id=event_id,
            assigned_to_user_id=assigned_to_user_id,
            created_by_user_id=created_by_user_id,
            error_message=None if server else "Failed to create on OpenStack",
        )
        self.session.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)

        return instance

    async def list_tracked_instances(
        self,
        page: int = 1,
        page_size: int = 50,
        event_id: int | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Instance], int]:
        """List tracked instances with filtering and pagination."""
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
                    Instance.openstack_id.ilike(f"%{search}%"),
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

    async def delete_and_track_instance(self, instance_id: int) -> bool:
        """Delete an instance from OpenStack and soft-delete the DB record."""
        instance = await self.get_tracked_instance(instance_id)
        if not instance:
            return False

        # Delete from OpenStack if it has an ID
        if instance.openstack_id:
            try:
                await self.delete_instance_on_openstack(instance.openstack_id)
            except Exception as e:
                logger.error("Failed to delete from OpenStack: %s", e)
                # Continue with soft-delete anyway

        instance.status = "DELETED"
        instance.deleted_at = datetime.now(timezone.utc)
        await self.session.commit()

        logger.info("Instance deleted: %s (id=%d)", instance.name, instance.id)
        return True

    async def sync_instance_status(self, instance_id: int) -> Optional[Instance]:
        """Refresh an instance's status from OpenStack."""
        instance = await self.get_tracked_instance(instance_id)
        if not instance or not instance.openstack_id:
            return instance

        try:
            server = await self.get_instance_status_from_openstack(instance.openstack_id)
            if server:
                instance.status = server.get("status", instance.status)
                # Extract IP
                addresses = server.get("addresses", {})
                for net_addrs in addresses.values():
                    for addr in net_addrs:
                        if addr.get("version") == 4:
                            instance.ip_address = addr["addr"]
                            break

                fault = server.get("fault")
                if fault:
                    instance.error_message = fault.get("message", "")
            else:
                # Server not found on OpenStack
                instance.status = "DELETED"
                instance.deleted_at = datetime.now(timezone.utc)

            await self.session.commit()
            await self.session.refresh(instance)
        except Exception as e:
            logger.error("Failed to sync instance %d status: %s", instance_id, e)

        return instance

    async def bulk_create_instances(
        self,
        count: int,
        name_prefix: str,
        flavor_id: str | None = None,
        image_id: str | None = None,
        network_id: str | None = None,
        key_name: str | None = None,
        template_id: int | None = None,
        license_product_id: int | None = None,
        event_id: int | None = None,
        created_by_user_id: int | None = None,
        user_data: str | None = None,
        ssh_public_key: str | None = None,
    ) -> tuple[int, list[str]]:
        """Bulk-create instances. Returns (success_count, error_messages)."""
        successes = 0
        errors = []

        for i in range(1, count + 1):
            name = f"{name_prefix}-{i:03d}"
            try:
                await self.create_and_track_instance(
                    name=name,
                    flavor_id=flavor_id,
                    image_id=image_id,
                    network_id=network_id,
                    key_name=key_name,
                    template_id=template_id,
                    license_product_id=license_product_id,
                    event_id=event_id,
                    created_by_user_id=created_by_user_id,
                    user_data=user_data,
                    ssh_public_key=ssh_public_key,
                )
                successes += 1
            except Exception as e:
                errors.append(f"{name}: {e}")
                logger.error("Failed to create instance %s: %s", name, e)

        return successes, errors

    async def bulk_delete_instances(self, instance_ids: list[int]) -> tuple[int, list[str]]:
        """Bulk-delete instances. Returns (success_count, error_messages)."""
        successes = 0
        errors = []

        for instance_id in instance_ids:
            try:
                ok = await self.delete_and_track_instance(instance_id)
                if ok:
                    successes += 1
                else:
                    errors.append(f"Instance {instance_id}: not found")
            except Exception as e:
                errors.append(f"Instance {instance_id}: {e}")

        return successes, errors

    async def get_instance_stats(self, event_id: int | None = None) -> dict:
        """Get instance statistics."""
        conditions = [Instance.deleted_at.is_(None)]
        if event_id:
            conditions.append(Instance.event_id == event_id)

        total_q = select(func.count(Instance.id)).where(*conditions)
        total = (await self.session.execute(total_q)).scalar() or 0

        active_q = select(func.count(Instance.id)).where(
            *conditions, Instance.status == "ACTIVE"
        )
        active = (await self.session.execute(active_q)).scalar() or 0

        building_q = select(func.count(Instance.id)).where(
            *conditions, Instance.status == "BUILDING"
        )
        building = (await self.session.execute(building_q)).scalar() or 0

        error_q = select(func.count(Instance.id)).where(
            *conditions, Instance.status == "ERROR"
        )
        errored = (await self.session.execute(error_q)).scalar() or 0

        return {
            "total": total,
            "active": active,
            "building": building,
            "error": errored,
            "shutoff": total - active - building - errored,
        }
