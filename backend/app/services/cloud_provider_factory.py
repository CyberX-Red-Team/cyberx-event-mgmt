"""Factory for creating cloud provider service instances."""
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.openstack_service import OpenStackService
from app.services.digitalocean_service import DigitalOceanService


class CloudProviderFactory:
    """Factory for instantiating the correct cloud provider service."""

    @staticmethod
    def get_provider(provider: str, session: AsyncSession):
        """Get appropriate cloud provider service.

        Args:
            provider: Provider name ('openstack' or 'digitalocean')
            session: Database session

        Returns:
            Provider service instance implementing CloudProviderInterface

        Raises:
            ValueError: If provider is unknown
        """
        if provider == "openstack":
            return OpenStackService(session)
        elif provider == "digitalocean":
            return DigitalOceanService(session)
        else:
            raise ValueError(
                f"Unknown cloud provider: {provider}. "
                f"Supported providers: openstack, digitalocean"
            )
