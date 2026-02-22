"""Instance management API routes."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_current_admin_user
from app.api.exceptions import not_found, bad_request, server_error
from app.api.utils.dependencies import get_openstack_service
from app.models.user import User
from app.services.openstack_service import OpenStackService
from app.schemas.instance import (
    InstanceCreate,
    InstanceBulkCreate,
    InstanceResponse,
    InstanceListResponse,
    InstanceStats,
    BulkDeleteRequest,
    BulkOperationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/instances", tags=["Instance Management"])


# ── Instance CRUD ──────────────────────────────────────────

@router.get("", response_model=InstanceListResponse)
async def list_instances(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    event_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """List instances (paginated, filterable)."""
    instances, total = await service.list_tracked_instances(
        page=page,
        page_size=page_size,
        event_id=event_id,
        status=status,
        search=search,
    )

    total_pages = (total + page_size - 1) // page_size

    # Build response items with event_name and created_by_username
    items = []
    for instance in instances:
        item_dict = InstanceResponse.model_validate(instance).model_dump()
        # Add event name if event exists
        if instance.event:
            item_dict["event_name"] = f"{instance.event.year} - {instance.event.name}"
        # Add creator username if exists
        if instance.created_by:
            item_dict["created_by_username"] = instance.created_by.username
        items.append(InstanceResponse(**item_dict))

    return InstanceListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=InstanceResponse, status_code=201)
async def create_instance(
    data: InstanceCreate,
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """Create a single instance."""
    try:
        instance = await service.create_and_track_instance(
            name=data.name,
            flavor_id=data.flavor_id,
            image_id=data.image_id,
            network_id=data.network_id,
            key_name=data.key_name,
            template_id=data.cloud_init_template_id,
            license_product_id=data.license_product_id,
            event_id=data.event_id,
            assigned_to_user_id=data.assigned_to_user_id,
            created_by_user_id=current_user.id,
            ssh_public_key=data.ssh_public_key,
        )
    except ValueError as e:
        raise bad_request(str(e))
    except Exception as e:
        logger.error("Failed to create instance: %s", e)
        raise server_error("Failed to create instance")

    return InstanceResponse.model_validate(instance)


@router.post("/bulk", response_model=BulkOperationResponse, status_code=201)
async def bulk_create_instances(
    data: InstanceBulkCreate,
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """Bulk create instances."""
    try:
        success_count, errors = await service.bulk_create_instances(
            count=data.count,
            name_prefix=data.name_prefix,
            flavor_id=data.flavor_id,
            image_id=data.image_id,
            network_id=data.network_id,
            key_name=data.key_name,
            template_id=data.cloud_init_template_id,
            license_product_id=data.license_product_id,
            event_id=data.event_id,
            created_by_user_id=current_user.id,
            ssh_public_key=data.ssh_public_key,
        )
    except ValueError as e:
        raise bad_request(str(e))

    return BulkOperationResponse(success_count=success_count, errors=errors)


@router.get("/stats", response_model=InstanceStats)
async def get_instance_stats(
    event_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """Get instance statistics."""
    stats = await service.get_instance_stats(event_id=event_id)
    return InstanceStats(**stats)


@router.get("/resources/flavors")
async def list_flavors(
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """List available OpenStack flavors."""
    try:
        flavors = await service.list_flavors()
    except Exception as e:
        logger.error("Failed to list flavors: %s", e)
        raise server_error("Failed to fetch flavors from OpenStack")
    return {"flavors": flavors}


@router.get("/resources/images")
async def list_images(
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """List available OpenStack images."""
    try:
        images = await service.list_images()
    except Exception as e:
        logger.error("Failed to list images: %s", e)
        raise server_error("Failed to fetch images from OpenStack")
    return {"images": images}


@router.get("/resources/networks")
async def list_networks(
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """List available OpenStack networks."""
    try:
        networks = await service.list_networks()
    except Exception as e:
        logger.error("Failed to list networks: %s", e)
        raise server_error("Failed to fetch networks from OpenStack")
    return {"networks": networks}


@router.get("/{instance_id}", response_model=InstanceResponse)
async def get_instance(
    instance_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """Get a specific instance."""
    instance = await service.get_tracked_instance(instance_id)
    if not instance:
        raise not_found("Instance", instance_id)
    return InstanceResponse.model_validate(instance)


@router.delete("/{instance_id}")
async def delete_instance(
    instance_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """Delete (terminate) an instance."""
    ok = await service.delete_and_track_instance(instance_id)
    if not ok:
        raise not_found("Instance", instance_id)
    return {"success": True, "message": "Instance deleted"}


@router.post("/{instance_id}/sync", response_model=InstanceResponse)
async def sync_instance(
    instance_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """Refresh instance status from OpenStack."""
    instance = await service.sync_instance_status(instance_id)
    if not instance:
        raise not_found("Instance", instance_id)
    return InstanceResponse.model_validate(instance)


@router.post("/bulk-delete", response_model=BulkOperationResponse)
async def bulk_delete_instances(
    data: BulkDeleteRequest,
    current_user: User = Depends(get_current_admin_user),
    service: OpenStackService = Depends(get_openstack_service),
):
    """Bulk delete instances."""
    success_count, errors = await service.bulk_delete_instances(data.instance_ids)
    return BulkOperationResponse(success_count=success_count, errors=errors)
