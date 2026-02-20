"""Cloud-init template management API routes."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_current_admin_user
from app.api.exceptions import not_found, bad_request, conflict
from app.api.utils.dependencies import get_cloud_init_service
from app.models.user import User
from app.services.cloud_init_service import CloudInitService
from app.schemas.cloud_init import (
    CloudInitTemplateCreate,
    CloudInitTemplateUpdate,
    CloudInitTemplateResponse,
    CloudInitTemplateListResponse,
    CloudInitPreviewRequest,
    CloudInitPreviewResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cloud-init", tags=["Cloud-Init Templates"])


@router.get("/templates", response_model=CloudInitTemplateListResponse)
async def list_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_admin_user),
    service: CloudInitService = Depends(get_cloud_init_service),
):
    """List cloud-init templates (paginated)."""
    templates, total = await service.list_templates(page=page, page_size=page_size)
    total_pages = (total + page_size - 1) // page_size

    return CloudInitTemplateListResponse(
        items=[CloudInitTemplateResponse.model_validate(t) for t in templates],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("/templates", response_model=CloudInitTemplateResponse, status_code=201)
async def create_template(
    data: CloudInitTemplateCreate,
    current_user: User = Depends(get_current_admin_user),
    service: CloudInitService = Depends(get_cloud_init_service),
):
    """Create a new cloud-init template."""
    try:
        template = await service.create_template(
            name=data.name,
            content=data.content,
            description=data.description,
            is_default=data.is_default,
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise conflict(f"Template with name '{data.name}' already exists")
        raise

    return CloudInitTemplateResponse.model_validate(template)


@router.get("/templates/{template_id}", response_model=CloudInitTemplateResponse)
async def get_template(
    template_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: CloudInitService = Depends(get_cloud_init_service),
):
    """Get a specific cloud-init template."""
    template = await service.get_template(template_id)
    if not template:
        raise not_found("Cloud-init template", template_id)
    return CloudInitTemplateResponse.model_validate(template)


@router.put("/templates/{template_id}", response_model=CloudInitTemplateResponse)
async def update_template(
    template_id: int,
    data: CloudInitTemplateUpdate,
    current_user: User = Depends(get_current_admin_user),
    service: CloudInitService = Depends(get_cloud_init_service),
):
    """Update a cloud-init template."""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise bad_request("No fields to update")

    template = await service.update_template(template_id, **update_data)
    if not template:
        raise not_found("Cloud-init template", template_id)

    return CloudInitTemplateResponse.model_validate(template)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: CloudInitService = Depends(get_cloud_init_service),
):
    """Delete a cloud-init template."""
    ok = await service.delete_template(template_id)
    if not ok:
        raise not_found("Cloud-init template", template_id)
    return {"success": True, "message": "Template deleted"}


@router.post("/templates/{template_id}/preview", response_model=CloudInitPreviewResponse)
async def preview_template(
    template_id: int,
    data: CloudInitPreviewRequest,
    current_user: User = Depends(get_current_admin_user),
    service: CloudInitService = Depends(get_cloud_init_service),
):
    """Render a template with sample variables for preview."""
    template = await service.get_template(template_id)
    if not template:
        raise not_found("Cloud-init template", template_id)

    rendered = service.render_template(template.content, data.variables)
    return CloudInitPreviewResponse(rendered=rendered)
