"""Instance Template service for managing reusable instance configurations."""
import logging
from typing import Optional, List, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.instance_template import InstanceTemplate
from app.models.event import Event
from app.models.instance import Instance

logger = logging.getLogger(__name__)


class InstanceTemplateService:
    """Service for managing instance templates."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_template(
        self,
        name: str,
        event_id: int,
        provider: str,
        image_id: str,
        flavor_id: Optional[str] = None,
        network_id: Optional[str] = None,
        provider_size_slug: Optional[str] = None,
        provider_region: Optional[str] = None,
        cloud_init_template_id: Optional[int] = None,
        license_product_id: Optional[int] = None,
        description: Optional[str] = None,
        created_by_user_id: Optional[int] = None,
    ) -> InstanceTemplate:
        """Create a new instance template.

        Args:
            name: Template name
            event_id: Event to associate template with
            provider: Cloud provider (openstack, digitalocean)
            image_id: Image/snapshot ID
            flavor_id: OpenStack flavor ID (optional)
            network_id: OpenStack network ID (optional)
            provider_size_slug: DigitalOcean size slug (optional)
            provider_region: DigitalOcean region (optional)
            cloud_init_template_id: Cloud-init template to use (optional)
            license_product_id: License product to assign (optional)
            description: Template description (optional)
            created_by_user_id: User creating the template (optional)

        Returns:
            Created InstanceTemplate

        Raises:
            ValueError: If event not found or is archived
        """
        # Validate event is not archived
        event_result = await self.session.execute(
            select(Event).where(Event.id == event_id)
        )
        event = event_result.scalar_one_or_none()

        if not event:
            raise ValueError(f"Event {event_id} not found")

        if event.is_archived:
            raise ValueError("Cannot create template for archived event")

        template = InstanceTemplate(
            name=name,
            description=description,
            provider=provider,
            flavor_id=flavor_id,
            network_id=network_id,
            provider_size_slug=provider_size_slug,
            provider_region=provider_region,
            image_id=image_id,
            cloud_init_template_id=cloud_init_template_id,
            license_product_id=license_product_id,
            event_id=event_id,
            created_by_user_id=created_by_user_id,
        )

        self.session.add(template)
        await self.session.commit()
        await self.session.refresh(template)

        logger.info("Created instance template %s (id=%d) for event %d", name, template.id, event_id)
        return template

    async def list_templates(
        self,
        event_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[InstanceTemplate], int]:
        """List instance templates with filtering and pagination.

        Args:
            event_id: Filter by event (optional)
            is_active: Filter by active status (optional)
            page: Page number (1-indexed)
            page_size: Results per page

        Returns:
            Tuple of (templates list, total count)
        """
        conditions = []

        if event_id is not None:
            conditions.append(InstanceTemplate.event_id == event_id)
        if is_active is not None:
            conditions.append(InstanceTemplate.is_active == is_active)

        # Count
        count_q = select(func.count(InstanceTemplate.id))
        if conditions:
            count_q = count_q.where(and_(*conditions))
        total = (await self.session.execute(count_q)).scalar() or 0

        # Fetch with relationships
        offset = (page - 1) * page_size
        q = (
            select(InstanceTemplate)
            .options(
                selectinload(InstanceTemplate.event),
                selectinload(InstanceTemplate.cloud_init_template),
                selectinload(InstanceTemplate.license_product),
                selectinload(InstanceTemplate.created_by),
            )
            .order_by(InstanceTemplate.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )

        if conditions:
            q = q.where(and_(*conditions))

        result = await self.session.execute(q)
        templates = list(result.scalars().all())

        return templates, total

    async def get_template(self, template_id: int) -> Optional[InstanceTemplate]:
        """Get a single template by ID.

        Args:
            template_id: Template ID

        Returns:
            InstanceTemplate or None if not found
        """
        result = await self.session.execute(
            select(InstanceTemplate)
            .options(
                selectinload(InstanceTemplate.event),
                selectinload(InstanceTemplate.cloud_init_template),
                selectinload(InstanceTemplate.license_product),
            )
            .where(InstanceTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    async def update_template(
        self,
        template_id: int,
        **kwargs
    ) -> Optional[InstanceTemplate]:
        """Update an existing template.

        Args:
            template_id: Template ID
            **kwargs: Fields to update

        Returns:
            Updated InstanceTemplate or None if not found

        Raises:
            ValueError: If changing to archived event
        """
        template = await self.get_template(template_id)
        if not template:
            return None

        # Validate event is not archived if changing event_id
        if 'event_id' in kwargs and kwargs['event_id'] != template.event_id:
            event_result = await self.session.execute(
                select(Event).where(Event.id == kwargs['event_id'])
            )
            event = event_result.scalar_one_or_none()
            if not event or event.is_archived:
                raise ValueError("Cannot assign template to archived event")

        # Update fields
        for key, value in kwargs.items():
            if hasattr(template, key):
                setattr(template, key, value)

        await self.session.commit()
        await self.session.refresh(template)

        logger.info("Updated instance template %d", template_id)
        return template

    async def delete_template(self, template_id: int) -> bool:
        """Delete a template.

        Args:
            template_id: Template ID

        Returns:
            True if deleted, False if not found
        """
        template = await self.get_template(template_id)
        if not template:
            return False

        await self.session.delete(template)
        await self.session.commit()

        logger.info("Deleted instance template %d", template_id)
        return True

    async def get_instance_count(self, template_id: int) -> int:
        """Get count of instances created from this template.

        Args:
            template_id: Template ID

        Returns:
            Count of active instances (excludes soft-deleted)
        """
        result = await self.session.execute(
            select(func.count(Instance.id))
            .where(
                Instance.instance_template_id == template_id,
                Instance.deleted_at.is_(None)
            )
        )
        return result.scalar() or 0

    async def get_provider_instance_count(self, provider: str) -> int:
        """Get count of instances for a specific provider.

        Args:
            provider: Cloud provider name (openstack, digitalocean, etc.)

        Returns:
            Count of active instances for the provider (excludes soft-deleted)
        """
        result = await self.session.execute(
            select(func.count(Instance.id))
            .where(
                Instance.provider == provider,
                Instance.deleted_at.is_(None)
            )
        )
        return result.scalar() or 0

    async def get_provider_max_instances(self, provider: str) -> int:
        """Get maximum instances allowed for a provider.

        Args:
            provider: Cloud provider name (openstack, digitalocean, etc.)

        Returns:
            Maximum instances (0 = unlimited)
        """
        from app.models.app_setting import AppSetting

        setting_key = f"provider_max_instances_{provider}"
        result = await self.session.execute(
            select(AppSetting).where(AppSetting.key == setting_key)
        )
        setting = result.scalar_one_or_none()

        if setting and setting.value:
            try:
                return int(setting.value)
            except ValueError:
                logger.warning("Invalid value for %s: %s", setting_key, setting.value)
                return 0

        # Default to unlimited if not set
        return 0

    async def check_can_provision(
        self,
        template_id: int
    ) -> Tuple[bool, str]:
        """Check if a new instance can be provisioned from this template.

        Args:
            template_id: Template ID

        Returns:
            Tuple of (can_provision: bool, reason: str)
        """
        template = await self.get_template(template_id)

        if not template:
            return False, "Template not found"

        if not template.is_active:
            return False, "Template is not active"

        # Check event is active
        if not template.event.is_active:
            return False, "Event is not active"

        # Check if archived
        if template.event.is_archived:
            return False, "Event is archived"

        # Check provider-level instance limit
        provider_max = await self.get_provider_max_instances(template.provider)
        if provider_max > 0:
            current_count = await self.get_provider_instance_count(template.provider)
            if current_count >= provider_max:
                return False, f"Maximum instances ({provider_max}) reached for {template.provider} provider"

        return True, ""
