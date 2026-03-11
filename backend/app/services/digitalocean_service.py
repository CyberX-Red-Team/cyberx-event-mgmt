"""DigitalOcean Droplet management service."""
import logging
from typing import Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)


class DigitalOceanService:
    """DigitalOcean Droplet client (implements CloudProviderInterface)."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()
        self.api_url = "https://api.digitalocean.com/v2"

    def _check_configured(self):
        """Raise if DigitalOcean is not configured."""
        if not self.settings.DO_API_TOKEN:
            raise ValueError(
                "DigitalOcean is not configured. "
                "Set DO_API_TOKEN in environment."
            )

    def _headers(self) -> dict:
        """Get headers for DigitalOcean API requests."""
        return {
            "Authorization": f"Bearer {self.settings.DO_API_TOKEN}",
            "Content-Type": "application/json",
        }

    async def authenticate(self) -> bool:
        """Verify API token by fetching account info."""
        self._check_configured()

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.api_url}/account",
                headers=self._headers()
            )
            resp.raise_for_status()

        logger.info("DigitalOcean authentication successful")
        return True

    async def create_instance(
        self,
        name: str,
        size: str,
        image: str,
        region: str | None = None,
        network: str | None = None,  # Unused for DO
        key_name: str | None = None,
        user_data: str | None = None,
    ) -> Optional[dict]:
        """Create a Droplet via DigitalOcean API.

        Args:
            name: Droplet name
            size: Size slug (e.g., 's-1vcpu-1gb')
            image: Image slug or ID (e.g., 'ubuntu-22-04-x64')
            region: Region slug (e.g., 'nyc1')
            network: Ignored (DO uses default VPC)
            key_name: SSH key name or ID
            user_data: Cloud-init user data (plain text)

        Returns:
            Droplet dict with 'id', 'status', etc., or None on failure
        """
        self._check_configured()

        # Apply defaults
        region = region or self.settings.DO_DEFAULT_REGION
        size = size or self.settings.DO_DEFAULT_SIZE

        if not all([name, size, image, region]):
            raise ValueError(
                "name, size, image, and region are required for DigitalOcean"
            )

        droplet_data = {
            "name": name,
            "region": region,
            "size": size,
            "image": image,
            "backups": False,
            "ipv6": False,
            "monitoring": True,
        }

        # Add SSH keys (required to prevent password authentication)
        # Use provided key_name or fall back to default DO_SSH_KEY_ID
        ssh_key = key_name or self.settings.DO_SSH_KEY_ID
        if ssh_key:
            # Assume key is either an SSH key ID or fingerprint
            droplet_data["ssh_keys"] = [ssh_key]
            logger.info(
                "Using SSH key for droplet %s: %s (from %s)",
                name,
                ssh_key,
                "key_name parameter" if key_name else "DO_SSH_KEY_ID setting"
            )
        else:
            logger.warning(
                "No SSH key configured for DigitalOcean - "
                "droplet will have password authentication enabled. "
                "Set DO_SSH_KEY_ID in .env or provide key_name parameter."
            )

        # Add user_data (cloud-init)
        if user_data:
            # DigitalOcean accepts user_data as plain string
            droplet_data["user_data"] = user_data

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.api_url}/droplets",
                    json=droplet_data,
                    headers=self._headers(),
                )
                resp.raise_for_status()

            data = resp.json()
            if "droplet" not in data:
                logger.error("Unexpected DigitalOcean response: %s", data)
                return None

            droplet = data["droplet"]
            logger.info(
                "DigitalOcean droplet created: %s (id=%s)",
                name,
                droplet["id"]
            )
            return droplet

        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to create DigitalOcean droplet: %s - %s",
                e.response.status_code,
                e.response.text
            )
            return None
        except Exception as e:
            logger.error("Failed to create DigitalOcean droplet: %s", e)
            return None

    async def delete_instance(self, droplet_id: str) -> bool:
        """Delete a Droplet via DigitalOcean API."""
        self._check_configured()

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.delete(
                    f"{self.api_url}/droplets/{droplet_id}",
                    headers=self._headers(),
                )

            if resp.status_code in (204, 404):
                logger.info("DigitalOcean droplet deleted: %s", droplet_id)
                return True

            logger.error(
                "Failed to delete droplet %s: %d",
                droplet_id,
                resp.status_code
            )
            return False

        except Exception as e:
            logger.error("Failed to delete droplet %s: %s", droplet_id, e)
            return False

    async def get_instance_status(self, droplet_id: str) -> Optional[dict]:
        """Get Droplet details from DigitalOcean API."""
        self._check_configured()

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.api_url}/droplets/{droplet_id}",
                    headers=self._headers(),
                )

            if resp.status_code == 404:
                return None

            resp.raise_for_status()
            return resp.json().get("droplet")

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error(
                "Failed to get droplet %s status: %s",
                droplet_id,
                e
            )
            return None
        except Exception as e:
            logger.error("Failed to get droplet %s status: %s", droplet_id, e)
            return None

    async def list_sizes(self) -> list[dict]:
        """List available DigitalOcean sizes."""
        self._check_configured()

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.api_url}/sizes",
                    headers=self._headers(),
                )
                resp.raise_for_status()

            return resp.json().get("sizes", [])

        except Exception as e:
            logger.error("Failed to list DigitalOcean sizes: %s", e)
            return []

    async def list_images(self) -> list[dict]:
        """List available DigitalOcean images (distribution images only)."""
        self._check_configured()

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.api_url}/images?type=distribution",
                    headers=self._headers(),
                )
                resp.raise_for_status()

            return resp.json().get("images", [])

        except Exception as e:
            logger.error("Failed to list DigitalOcean images: %s", e)
            return []

    async def list_regions_or_networks(self) -> list[dict]:
        """List available DigitalOcean regions."""
        self._check_configured()

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.api_url}/regions",
                    headers=self._headers(),
                )
                resp.raise_for_status()

            return resp.json().get("regions", [])

        except Exception as e:
            logger.error("Failed to list DigitalOcean regions: %s", e)
            return []

    def normalize_status(self, provider_status: str) -> str:
        """Normalize DigitalOcean status to standard status codes.

        DO statuses: new, active, off, archive
        Standard: BUILDING, ACTIVE, ERROR, SHUTOFF, DELETED
        """
        status_map = {
            "new": "BUILDING",
            "active": "ACTIVE",
            "off": "SHUTOFF",
            "archive": "DELETED",
        }
        normalized = status_map.get(provider_status.lower(), "BUILDING")
        return normalized

    def extract_ip_address(self, droplet_data: dict) -> str | None:
        """Extract public IPv4 address from Droplet data."""
        networks = droplet_data.get("networks", {})
        v4_networks = networks.get("v4", [])

        for network in v4_networks:
            if network.get("type") == "public":
                return network.get("ip_address")

        return None
