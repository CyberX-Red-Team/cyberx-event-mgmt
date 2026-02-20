"""Cloud-init template management service."""
import base64
import logging
import re
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cloud_init_template import CloudInitTemplate

logger = logging.getLogger(__name__)


class CloudInitService:
    """CRUD and rendering for cloud-init templates."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_templates(
        self, page: int = 1, page_size: int = 50
    ) -> tuple[list[CloudInitTemplate], int]:
        """List templates with pagination."""
        # Count
        count_q = select(func.count(CloudInitTemplate.id))
        total = (await self.session.execute(count_q)).scalar() or 0

        # Fetch
        offset = (page - 1) * page_size
        q = (
            select(CloudInitTemplate)
            .order_by(CloudInitTemplate.name)
            .offset(offset)
            .limit(page_size)
        )
        result = await self.session.execute(q)
        templates = list(result.scalars().all())

        return templates, total

    async def get_template(self, template_id: int) -> Optional[CloudInitTemplate]:
        """Get a single template by ID."""
        result = await self.session.execute(
            select(CloudInitTemplate).where(CloudInitTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    async def get_default_template(self) -> Optional[CloudInitTemplate]:
        """Get the default template (is_default=True)."""
        result = await self.session.execute(
            select(CloudInitTemplate).where(CloudInitTemplate.is_default == True)
        )
        return result.scalar_one_or_none()

    async def create_template(
        self, name: str, content: str, description: str | None = None, is_default: bool = False
    ) -> CloudInitTemplate:
        """Create a new cloud-init template."""
        if is_default:
            await self._clear_default()

        template = CloudInitTemplate(
            name=name,
            description=description,
            content=content,
            is_default=is_default,
        )
        self.session.add(template)
        await self.session.commit()
        await self.session.refresh(template)
        logger.info("Created cloud-init template: %s (id=%d)", name, template.id)
        return template

    async def update_template(self, template_id: int, **kwargs) -> Optional[CloudInitTemplate]:
        """Update a template by ID. Pass only fields to update."""
        template = await self.get_template(template_id)
        if not template:
            return None

        if kwargs.get("is_default"):
            await self._clear_default()

        for key, value in kwargs.items():
            if value is not None and hasattr(template, key):
                setattr(template, key, value)

        await self.session.commit()
        await self.session.refresh(template)
        logger.info("Updated cloud-init template: %s (id=%d)", template.name, template.id)
        return template

    async def delete_template(self, template_id: int) -> bool:
        """Delete a template by ID."""
        template = await self.get_template(template_id)
        if not template:
            return False

        await self.session.delete(template)
        await self.session.commit()
        logger.info("Deleted cloud-init template: %s (id=%d)", template.name, template_id)
        return True

    def render_template(self, content: str, variables: dict) -> str:
        """Render a cloud-init template by substituting {{variable}} placeholders.

        Args:
            content: Raw YAML template content with {{placeholders}}.
            variables: Dict of variable_name -> value.

        Returns:
            Rendered YAML string (not base64 encoded).
        """
        rendered = content
        for key, value in variables.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))

        # Warn about unsubstituted placeholders
        remaining = re.findall(r"\{\{(\w+)\}\}", rendered)
        if remaining:
            logger.warning(
                "Unsubstituted placeholders in cloud-init template: %s",
                ", ".join(remaining),
            )

        return rendered

    @staticmethod
    def encode_user_data(rendered_content: str) -> str:
        """Base64-encode rendered cloud-init content for Nova API.

        Raises:
            ValueError: If encoded data exceeds Nova's 65535-byte limit.
        """
        encoded = base64.b64encode(rendered_content.encode("utf-8")).decode("utf-8")
        if len(encoded) > 65535:
            raise ValueError(
                f"Encoded user_data is {len(encoded)} bytes, exceeds Nova's 65535-byte limit"
            )
        return encoded

    async def _clear_default(self):
        """Remove is_default from all templates."""
        result = await self.session.execute(
            select(CloudInitTemplate).where(CloudInitTemplate.is_default == True)
        )
        for t in result.scalars().all():
            t.is_default = False
