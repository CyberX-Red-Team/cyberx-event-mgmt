"""Participant self-service instance provisioning routes."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.dependencies import get_db, get_current_active_user
from app.api.exceptions import not_found, bad_request, forbidden, server_error
from app.models.user import User
from app.models.event import Event
from app.models.instance import Instance
from app.services.instance_service import InstanceService
from app.services.instance_template_service import InstanceTemplateService
from app.schemas.instance_template import (
    InstanceTemplateResponse,
    InstanceFromTemplateRequest,
)
from app.schemas.instance import InstanceResponse, InstanceListResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/participants", tags=["Participant Portal"])


async def get_instance_service(db: AsyncSession = Depends(get_db)) -> InstanceService:
    """Get InstanceService dependency."""
    return InstanceService(db)


async def get_template_service(db: AsyncSession = Depends(get_db)) -> InstanceTemplateService:
    """Get InstanceTemplateService dependency."""
    return InstanceTemplateService(db)


@router.get("/available-templates", response_model=list[InstanceTemplateResponse])
async def list_available_templates(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    service: InstanceTemplateService = Depends(get_template_service),
):
    """List instance templates available for participant provisioning.

    Requirements:
    - Event must be active
    - Event must have vpn_available=True
    - Template must be active
    """
    # Get active event
    result = await db.execute(
        select(Event).where(Event.is_active == True)
    )
    active_event = result.scalar_one_or_none()

    if not active_event:
        return []

    # Check VPN availability
    if not active_event.vpn_available:
        return []

    # List templates for active event
    templates, _ = await service.list_templates(
        event_id=active_event.id,
        is_active=True,
        page=1,
        page_size=100,
    )

    # Build responses with computed fields
    items = []
    for template in templates:
        item_dict = InstanceTemplateResponse.model_validate(template).model_dump()

        if template.cloud_init_template:
            item_dict["cloud_init_template_name"] = template.cloud_init_template.name
        if template.license_product:
            item_dict["license_product_name"] = template.license_product.name

        # Get instance count
        count = await service.get_instance_count(template.id)
        item_dict["current_instance_count"] = count

        items.append(InstanceTemplateResponse(**item_dict))

    return items


@router.post("/instances", response_model=InstanceResponse, status_code=201)
async def provision_instance(
    data: InstanceFromTemplateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    instance_service: InstanceService = Depends(get_instance_service),
    template_service: InstanceTemplateService = Depends(get_template_service),
):
    """Provision a new instance from a template (participant self-service).

    Requirements:
    - Event must be active
    - Event must have vpn_available=True
    - Template must be active and under max_instances limit
    """
    # Get template
    template = await template_service.get_template(data.template_id)
    if not template:
        raise not_found("Template", data.template_id)

    # Verify event is active
    if not template.event.is_active:
        raise bad_request("Event is not active")

    # Verify VPN is available
    if not template.event.vpn_available:
        raise bad_request("VPN system must be enabled for participant provisioning")

    # Check if template allows provisioning
    can_provision, reason = await template_service.check_can_provision(data.template_id)
    if not can_provision:
        raise bad_request(reason)

    # Create instance
    try:
        instance = await instance_service.create_from_template(
            template_id=data.template_id,
            name=data.name,
            assigned_to_user_id=current_user.id,
            created_by_user_id=current_user.id,
            visibility=data.visibility,
            notes=data.notes,
        )
    except ValueError as e:
        raise bad_request(str(e))
    except Exception as e:
        logger.error("Failed to provision instance: %s", e)
        raise server_error("Failed to provision instance")

    return InstanceResponse.model_validate(instance)


@router.get("/instances", response_model=InstanceListResponse)
async def list_my_instances(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
    service: InstanceService = Depends(get_instance_service),
):
    """List instances visible to the current participant.

    Shows:
    - Private instances created by the user
    - Shared/public instances from other participants
    """
    # Get user's private instances
    my_instances, my_total = await service.list_tracked_instances(
        page=1,
        page_size=1000,  # Get all for filtering
        created_by_user_id=current_user.id,
        status=status,
    )

    # Get shared/public instances from others
    result = await service.session.execute(
        select(Instance)
        .options(
            selectinload(Instance.event),
            selectinload(Instance.created_by),
            selectinload(Instance.instance_template)
        )
        .where(
            and_(
                Instance.deleted_at.is_(None),
                Instance.created_by_user_id != current_user.id,
                Instance.visibility == "public"
            )
        )
        .order_by(Instance.created_at.desc())
    )
    shared_instances = list(result.scalars().all())

    # Combine and paginate
    all_instances = my_instances + shared_instances
    total = len(all_instances)

    # Apply pagination
    start = (page - 1) * page_size
    end = start + page_size
    instances = all_instances[start:end]

    total_pages = (total + page_size - 1) // page_size

    # Build responses
    items = []
    for instance in instances:
        item_dict = InstanceResponse.model_validate(instance).model_dump()

        if instance.event:
            item_dict["event_name"] = f"{instance.event.year} - {instance.event.name}"
        if instance.created_by:
            item_dict["created_by_username"] = instance.created_by.pandas_username or instance.created_by.email
        if instance.instance_template:
            item_dict["instance_template_name"] = instance.instance_template.name

        items.append(InstanceResponse(**item_dict))

    return InstanceListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.delete("/instances/{instance_id}")
async def delete_my_instance(
    instance_id: int,
    current_user: User = Depends(get_current_active_user),
    service: InstanceService = Depends(get_instance_service),
):
    """Delete an instance.

    Permissions:
    - Can delete own private instances
    - Can delete own shared/public instances (creator only)
    - Cannot delete other users' shared/public instances
    """
    instance = await service.get_tracked_instance(instance_id)

    if not instance:
        raise not_found("Instance", instance_id)

    # Check ownership
    is_creator = instance.created_by_user_id == current_user.id

    if not is_creator:
        raise forbidden("You can only delete instances you created")

    # Delete
    ok = await service.delete_and_track_instance(instance_id)
    if not ok:
        raise server_error("Failed to delete instance")

    return {"success": True, "message": "Instance deleted"}


@router.patch("/instances/{instance_id}", response_model=InstanceResponse)
async def update_my_instance(
    instance_id: int,
    visibility: Optional[str] = None,
    notes: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    service: InstanceService = Depends(get_instance_service),
):
    """Update instance visibility and notes.

    Permissions:
    - Only creator can update their instances
    """
    instance = await service.get_tracked_instance(instance_id)

    if not instance:
        raise not_found("Instance", instance_id)

    # Check ownership
    if instance.created_by_user_id != current_user.id:
        raise forbidden("You can only update instances you created")

    # Validate visibility if provided
    if visibility is not None:
        if visibility not in ["private", "public"]:
            raise bad_request("Invalid visibility. Must be private or public")
        instance.visibility = visibility

    # Update notes if provided
    if notes is not None:
        instance.notes = notes

    # Save changes
    await db.commit()
    await db.refresh(instance)

    return InstanceResponse.model_validate(instance)


@router.post("/instances/{instance_id}/sync", response_model=InstanceResponse)
async def sync_my_instance(
    instance_id: int,
    current_user: User = Depends(get_current_active_user),
    service: InstanceService = Depends(get_instance_service),
):
    """Sync instance status from cloud provider.

    Permissions:
    - Can sync own instances or public instances
    """
    instance = await service.get_tracked_instance(instance_id)

    if not instance:
        raise not_found("Instance", instance_id)

    # Check if user can access this instance
    is_owner = instance.created_by_user_id == current_user.id
    is_public = instance.visibility == "public"

    if not (is_owner or is_public):
        raise forbidden("You can only sync your own instances or public instances")

    # Sync status
    synced_instance = await service.sync_instance_status(instance_id)
    if not synced_instance:
        raise server_error("Failed to sync instance status")

    return InstanceResponse.model_validate(synced_instance)
