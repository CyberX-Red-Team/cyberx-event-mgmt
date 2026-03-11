"""Cloud provider protocol defining the interface all providers must implement."""
from typing import Protocol, Optional


class CloudProviderInterface(Protocol):
    """Protocol defining the contract for cloud provider services.

    All cloud provider services (OpenStack, DigitalOcean, AWS, etc.) must
    implement these methods to work with the unified InstanceService.
    """

    async def authenticate(self) -> bool:
        """Authenticate with the cloud provider.

        Returns:
            True if authentication successful, raises exception otherwise
        """
        ...

    async def create_instance(
        self,
        name: str,
        size: str,
        image: str,
        region: str | None = None,
        network: str | None = None,
        key_name: str | None = None,
        user_data: str | None = None,
    ) -> Optional[dict]:
        """Create instance on the cloud provider.

        Args:
            name: Instance name
            size: Instance size/flavor (e.g., 'm1.small' or 's-1vcpu-1gb')
            image: Image ID or slug
            region: Region/availability zone (required for DO, optional for OS)
            network: Network ID (required for OpenStack, ignored for DO)
            key_name: SSH key name or ID
            user_data: Cloud-init user data (plain text)

        Returns:
            Provider-specific instance dict with 'id' and 'status' keys,
            or None if creation failed
        """
        ...

    async def delete_instance(self, instance_id: str) -> bool:
        """Delete instance by provider ID.

        Args:
            instance_id: Provider's instance UUID/ID

        Returns:
            True if deleted successfully
        """
        ...

    async def get_instance_status(self, instance_id: str) -> Optional[dict]:
        """Get instance status from provider.

        Args:
            instance_id: Provider's instance UUID/ID

        Returns:
            Provider-specific instance dict with status info,
            or None if instance not found
        """
        ...

    async def list_sizes(self) -> list[dict]:
        """List available instance sizes/flavors.

        Returns:
            List of size/flavor dicts (provider-specific format)
        """
        ...

    async def list_images(self) -> list[dict]:
        """List available images.

        Returns:
            List of image dicts (provider-specific format)
        """
        ...

    async def list_regions_or_networks(self) -> list[dict]:
        """List regions (DigitalOcean) or networks (OpenStack).

        Returns:
            List of region/network dicts (provider-specific format)
        """
        ...

    def normalize_status(self, provider_status: str) -> str:
        """Normalize provider-specific status to standard status codes.

        Standard statuses: BUILDING, ACTIVE, ERROR, SHUTOFF, DELETED

        Args:
            provider_status: Provider's status string

        Returns:
            Normalized status (BUILDING, ACTIVE, ERROR, SHUTOFF, DELETED)
        """
        ...

    def extract_ip_address(self, instance_data: dict) -> str | None:
        """Extract IP address from provider instance data.

        Args:
            instance_data: Provider-specific instance dict

        Returns:
            Primary IPv4 address or None
        """
        ...
