"""Instance Template management API routes (Admin-only)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_current_admin_user
from app.api.exceptions import not_found, bad_request, server_error
from app.models.user import User
from app.services.instance_template_service import InstanceTemplateService
from app.schemas.instance_template import (
    InstanceTemplateCreate,
    InstanceTemplateUpdate,
    InstanceTemplateResponse,
    InstanceTemplateListResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/instance-templates", tags=["Instance Templates (Admin)"])


async def get_template_service(db: AsyncSession = Depends(get_db)) -> InstanceTemplateService:
    """Get InstanceTemplateService dependency."""
    return InstanceTemplateService(db)


@router.get("", response_model=InstanceTemplateListResponse)
async def list_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    event_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(None),
    current_user: User = Depends(get_current_admin_user),
    service: InstanceTemplateService = Depends(get_template_service),
):
    """List instance templates with filtering and pagination."""
    templates, total = await service.list_templates(
        event_id=event_id,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )

    total_pages = (total + page_size - 1) // page_size

    # Build responses with computed fields
    items = []
    for template in templates:
        item_dict = InstanceTemplateResponse.model_validate(template).model_dump()

        # Add computed fields
        if template.event:
            item_dict["event_name"] = f"{template.event.year} - {template.event.name}"
        if template.cloud_init_template:
            item_dict["cloud_init_template_name"] = template.cloud_init_template.name
        if template.license_product:
            item_dict["license_product_name"] = template.license_product.name
        if template.created_by:
            item_dict["created_by_username"] = template.created_by.pandas_username or template.created_by.email

        items.append(InstanceTemplateResponse(**item_dict))

    return InstanceTemplateListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=InstanceTemplateResponse, status_code=201)
async def create_template(
    data: InstanceTemplateCreate,
    current_user: User = Depends(get_current_admin_user),
    service: InstanceTemplateService = Depends(get_template_service),
):
    """Create a new instance template."""
    try:
        template = await service.create_template(
            name=data.name,
            description=data.description,
            provider=data.provider,
            flavor_id=data.flavor_id,
            network_id=data.network_id,
            provider_size_slug=data.provider_size_slug,
            provider_region=data.provider_region,
            image_id=data.image_id,
            cloud_init_template_id=data.cloud_init_template_id,
            license_product_id=data.license_product_id,
            event_id=data.event_id,
            created_by_user_id=current_user.id,
        )
    except ValueError as e:
        raise bad_request(str(e))
    except Exception as e:
        logger.error("Failed to create template: %s", e)
        raise server_error("Failed to create template")

    return InstanceTemplateResponse.model_validate(template)


@router.get("/{template_id}", response_model=InstanceTemplateResponse)
async def get_template(
    template_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: InstanceTemplateService = Depends(get_template_service),
):
    """Get a specific template."""
    template = await service.get_template(template_id)
    if not template:
        raise not_found("Template", template_id)

    return InstanceTemplateResponse.model_validate(template)


@router.patch("/{template_id}", response_model=InstanceTemplateResponse)
async def update_template(
    template_id: int,
    data: InstanceTemplateUpdate,
    current_user: User = Depends(get_current_admin_user),
    service: InstanceTemplateService = Depends(get_template_service),
):
    """Update a template."""
    try:
        template = await service.update_template(
            template_id,
            **data.model_dump(exclude_unset=True)
        )
        if not template:
            raise not_found("Template", template_id)
    except ValueError as e:
        raise bad_request(str(e))

    return InstanceTemplateResponse.model_validate(template)


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: InstanceTemplateService = Depends(get_template_service),
):
    """Delete a template."""
    ok = await service.delete_template(template_id)
    if not ok:
        raise not_found("Template", template_id)

    return {"success": True, "message": "Template deleted"}
