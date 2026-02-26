"""Admin API routes for participant management."""
import logging
import secrets
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.api.exceptions import not_found, forbidden, bad_request, conflict, unauthorized, server_error

from app.dependencies import (
    get_db,
    get_current_admin_user,
    get_current_sponsor_user,
    get_current_active_user,
    permissions
)
from app.api.utils.request import extract_client_metadata
from app.api.utils.pagination import calculate_pagination
from app.api.utils.response_builders import build_participant_response
from app.api.utils.dependencies import (
    get_participant_service,
    get_vpn_service
)
from app.models.user import User, UserRole
from app.models.vpn import VPNCredential
from app.services.participant_service import ParticipantService
from app.services.audit_service import AuditService
from app.schemas.participant import (
    ParticipantCreate,
    ParticipantUpdate,
    ParticipantResponse,
    ParticipantListResponse,
    ParticipantStats,
    BulkActionRequest,
    BulkActionResponse,
    PasswordResetRequest,
    PasswordResetResponse,
    SponsorInfo,
    UserRoleEnum,
    RoleUpdateRequest,
    SponsorAssignRequest,
    MySponsoredParticipantsResponse,
)
from app.schemas.vpn import VPNStats
from app.schemas.dashboard import DashboardStats, DashboardResponse
from app.schemas.audit import (
    AuditLogResponse,
    AuditLogListResponse,
    AuditLogStats
)
from app.models.audit_log import AuditLog
from app.models.email_queue import EmailQueue, EmailBatchLog, EmailQueueStatus
from app.services.email_queue_service import EmailQueueService
from datetime import datetime, timedelta, timezone, date
from app.services.vpn_service import VPNService


router = APIRouter(prefix="/api/admin", tags=["Admin"])
logger = logging.getLogger(__name__)


@router.get("/participants", response_model=ParticipantListResponse)
async def list_participants(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search term"),
    confirmed: Optional[str] = Query(None, description="Filter by confirmed status"),
    has_vpn: Optional[bool] = Query(None, description="Filter by VPN status"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    email_status: Optional[str] = Query(None, description="Filter by email status"),
    role: Optional[str] = Query(None, description="Filter by role"),
    country: Optional[str] = Query(None, description="Filter by country"),
    sponsor_id: Optional[int] = Query(None, description="Filter by sponsor ID"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    List participants with filtering and pagination.

    - Admins and sponsors can see all participants
    - Sponsors can only edit/delete participants they sponsor
    """
    participants, total = await service.list_participants(
        page=page,
        page_size=page_size,
        search=search,
        confirmed=confirmed,
        has_vpn=has_vpn,
        is_active=is_active,
        email_status=email_status,
        sort_by=sort_by,
        sort_order=sort_order,
        role=role,
        country=country,
        sponsor_id=sponsor_id
    )

    # Build responses with VPN info
    items = []
    for p in participants:
        item = await build_participant_response(p, db)
        items.append(item)

    _, total_pages = calculate_pagination(total, page, page_size)

    return ParticipantListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/participants/stats", response_model=ParticipantStats)
async def get_participant_stats(
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service)
):
    """
    Get participant statistics for the dashboard.

    Both admins and sponsors see stats for all participants.
    """
    stats = await service.get_statistics()
    return ParticipantStats(**stats)


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(get_current_sponsor_user),
    participant_service: ParticipantService = Depends(get_participant_service),
    vpn_service: VPNService = Depends(get_vpn_service)
):
    """
    Get combined dashboard statistics.

    Both admins and sponsors see all stats.
    """
    participant_stats = await participant_service.get_statistics()
    vpn_stats = await vpn_service.get_statistics()

    return DashboardResponse(
        stats=DashboardStats(
            participants=ParticipantStats(**participant_stats),
            vpn=VPNStats(**vpn_stats)
        ),
        recent_participants=[],
        recent_vpn_assignments=[]
    )


@router.get("/participants/{participant_id}", response_model=ParticipantResponse)
async def get_participant(
    participant_id: int,
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific participant by ID."""
    participant = await service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant")

    # Check permission to view this participant
    permissions.can_view_participant(current_user, participant)

    return await build_participant_response(participant, db)


@router.post("/participants", response_model=ParticipantResponse, status_code=status.HTTP_201_CREATED)
async def create_participant(
    data: ParticipantCreate,
    request: Request,
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new participant.

    - Admins can create participants with any role and sponsor
    - Sponsors can only create participants with themselves as sponsor
    """
    # Check if email already exists
    existing = await service.get_participant_by_email(data.email)
    if existing:
        raise bad_request("A participant with this email already exists")

    # Determine sponsor_id
    sponsor_id = data.sponsor_id
    if not current_user.is_admin_role:
        # Sponsors can only create participants they sponsor
        sponsor_id = current_user.id
        # Sponsors cannot create admin or sponsor role users
        if data.role in (UserRoleEnum.ADMIN, UserRoleEnum.SPONSOR):
            raise forbidden("Only administrators can create admin or sponsor users")

    # Convert role enum to string value
    role_value = data.role.value if data.role else UserRole.INVITEE.value

    participant = await service.create_participant(
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
        country=data.country,
        confirmed=data.confirmed,
        pandas_username=data.pandas_username,
        pandas_password=data.pandas_password,
        discord_username=data.discord_username,
        sponsor_email=data.sponsor_email,
        sponsor_id=sponsor_id,
        role=role_value,
        is_admin=data.is_admin
    )

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    audit_service = AuditService(db)
    await audit_service.log_user_create(
        user_id=current_user.id,
        created_user_id=participant.id,
        details={
            "email": data.email,
            "role": role_value,
            "sponsor_id": sponsor_id
        },
        ip_address=ip_address,
        user_agent=user_agent
    )

    # Reload participant with relationships for response
    participant = await service.get_participant(participant.id)

    # Trigger workflow for admin/sponsor creation (send welcome email with portal password)
    if participant.role in [UserRole.ADMIN.value, UserRole.SPONSOR.value]:
        from app.services.workflow_service import WorkflowService
        from app.models.email_workflow import WorkflowTriggerEvent
        from app.utils.password import generate_password, hash_password
        from app.config import get_settings

        settings = get_settings()
        workflow_service = WorkflowService(db)

        # Determine trigger event based on role
        trigger_event = (
            WorkflowTriggerEvent.ADMIN_CREATED
            if participant.role == UserRole.ADMIN.value
            else WorkflowTriggerEvent.SPONSOR_CREATED
        )

        # Generate temporary password for web portal login
        temp_password = generate_password(length=12)
        participant.password_hash = hash_password(temp_password)
        await db.commit()

        # Role-specific template variables (see docs/email-template-variables.md)
        ROLE_TEMPLATE_VARS = {
            UserRole.ADMIN.value: {
                "role": "Admin",
                "role_label": "ADMIN",
                "role_upper": "ADMINISTRATOR",
                "role_display": "Administrator",
                "a_or_an": "an",
            },
            UserRole.SPONSOR.value: {
                "role": "Sponsor",
                "role_label": "SPONSOR",
                "role_upper": "SPONSOR",
                "role_display": "Sponsor",
                "a_or_an": "a",
            },
        }

        # Trigger workflow with custom variables
        await workflow_service.trigger_workflow(
            trigger_event=trigger_event,
            user_id=participant.id,
            custom_vars={
                "first_name": participant.first_name,
                "last_name": participant.last_name,
                **ROLE_TEMPLATE_VARS[participant.role],
                "password": temp_password,  # Web portal password, not pandas
                "support_email": settings.SENDGRID_FROM_EMAIL
            }
        )

        logger.info(f"Triggered {trigger_event} workflow for new {participant.role} {participant.id}")

    # Check if there's an active event and queue invitation email
    from app.services.event_service import EventService
    event_service = EventService(db)
    active_event = await event_service.get_active_event()

    # Determine if invitation should be sent based on event settings
    should_send_invitation = False
    if active_event and participant.role in ['invitee', 'sponsor']:
        # Check EventParticipation status for current event
        from app.models.event import ParticipationStatus
        participation = await participant.get_current_event_participation(db)

        # Send only if not yet confirmed/declined (invited, no_response, or no record yet)
        if not participation or participation.status in [
            ParticipationStatus.INVITED.value,
            ParticipationStatus.NO_RESPONSE.value
        ]:
            # TEST MODE ALWAYS RESTRICTS: Only send to sponsors if test mode is enabled
            if active_event.test_mode:
                should_send_invitation = (participant.role == 'sponsor')
            else:
                # Normal mode: Send if registration is open
                should_send_invitation = active_event.registration_open

    if should_send_invitation:
        # Queue invitation email using helper function
        from app.services.email_service import queue_invitation_email_for_user

        await queue_invitation_email_for_user(
            user=participant,
            event=active_event,
            session=db,
            force=False
        )
        await db.commit()

        logger.info(f"Queued invitation email for new participant {participant.id}")

    # Note: Invitation blocking is logged in participant_service.create_participant()
    return await build_participant_response(participant, db)


@router.put("/participants/{participant_id}", response_model=ParticipantResponse)
async def update_participant(
    participant_id: int,
    data: ParticipantUpdate,
    request: Request,
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a participant.

    - Admins can update any participant
    - Sponsors can update participants they sponsor (except role and sponsor_id)

    NOTE: Username (pandas_username) is auto-generated and cannot be manually edited.
    """
    # Get the participant first to check permissions
    participant = await service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant")

    # Check permission to edit this participant
    permissions.can_edit_participant(current_user, participant)

    # Sponsors cannot change role or sponsor_id
    if not current_user.is_admin_role:
        if data.role is not None:
            raise forbidden("Only administrators can change user roles")
        if data.sponsor_id is not None:
            raise forbidden("Only administrators can change sponsor assignments")

    # Check if email is being changed to one that already exists
    if data.email:
        existing = await service.get_participant_by_email(data.email)
        if existing and existing.id != participant_id:
            raise bad_request("A participant with this email already exists")

    # Convert role enum to string value if provided
    update_data = data.model_dump(exclude_unset=True)
    if 'role' in update_data and update_data['role'] is not None:
        update_data['role'] = update_data['role'].value

    participant = await service.update_participant(
        participant_id,
        **update_data
    )

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    audit_service = AuditService(db)
    await audit_service.log_user_update(
        user_id=current_user.id,
        updated_user_id=participant_id,
        changes=update_data,
        ip_address=ip_address,
        user_agent=user_agent
    )

    return await build_participant_response(participant, db)


@router.delete("/participants/{participant_id}")
async def delete_participant(
    participant_id: int,
    request: Request,
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a participant.

    - Admins can delete any participant
    - Sponsors can only delete participants they sponsor
    """
    # Get the participant first to check permissions
    participant = await service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant")

    # Check permission to delete this participant
    permissions.can_delete_participant(current_user, participant)

    # Store details before deletion
    deleted_user_email = participant.email
    deleted_user_name = f"{participant.first_name} {participant.last_name}"

    success = await service.delete_participant(participant_id)
    if not success:
        raise not_found("Participant")

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    audit_service = AuditService(db)
    await audit_service.log_user_delete(
        user_id=current_user.id,
        deleted_user_id=participant_id,
        details={
            "email": deleted_user_email,
            "name": deleted_user_name
        },
        ip_address=ip_address,
        user_agent=user_agent
    )

    return {"message": "Participant deleted successfully"}


@router.post("/participants/bulk", response_model=BulkActionResponse)
async def bulk_action(
    data: BulkActionRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Perform bulk actions on participants.

    Requires admin role.
    """
    audit_service = AuditService(db)

    if data.action == "activate":
        count, failed = await service.bulk_activate(data.participant_ids)

        # Audit log
        ip_address, user_agent = extract_client_metadata(request)
        await audit_service.log_bulk_action(
            user_id=current_user.id,
            action="activate",
            affected_user_ids=data.participant_ids,
            ip_address=ip_address,
            user_agent=user_agent
        )

        return BulkActionResponse(
            success=True,
            message=f"Activated {count} participants",
            affected_count=count,
            failed_ids=failed
        )
    elif data.action == "deactivate":
        count, failed = await service.bulk_deactivate(data.participant_ids)

        # Audit log
        ip_address, user_agent = extract_client_metadata(request)
        await audit_service.log_bulk_action(
            user_id=current_user.id,
            action="deactivate",
            affected_user_ids=data.participant_ids,
            ip_address=ip_address,
            user_agent=user_agent
        )

        return BulkActionResponse(
            success=True,
            message=f"Deactivated {count} participants",
            affected_count=count,
            failed_ids=failed
        )
    else:
        raise bad_request(f"Unknown action: {data.action}")


@router.post("/participants/{participant_id}/reset-password", response_model=PasswordResetResponse)
async def reset_participant_password(
    participant_id: int,
    request: Request,
    send_email: bool = Query(True, description="Send password email to participant"),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Reset a participant's password.

    - Admins can reset any participant's password
    - Sponsors can only reset passwords for participants they sponsor
    """
    # Get the participant first to check permissions
    participant = await service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant")

    # Check permission to edit this participant
    permissions.can_edit_participant(current_user, participant)

    success, new_password = await service.reset_password(participant_id)

    if not success:
        raise not_found("Participant")

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    audit_service = AuditService(db)
    await audit_service.log_password_reset(
        user_id=current_user.id,
        target_user_id=participant_id,
        ip_address=ip_address,
        user_agent=user_agent
    )

    # TODO: Send email if send_email is True

    return PasswordResetResponse(
        success=True,
        message="Password reset successfully" + (" (email sent)" if send_email else ""),
        new_password=new_password if not send_email else None
    )


@router.post("/participants/{participant_id}/resend-invitation")
async def resend_participant_invitation(
    participant_id: int,
    request: Request,
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Resend invitation email to a participant.

    - Admins can resend invitations to any participant
    - Sponsors can only resend invitations to participants they sponsor
    - Generates a new confirmation code and bypasses 24-hour duplicate protection
    - Only sends to participants with role 'invitee' or 'sponsor' who haven't confirmed yet
    """
    # Get the participant first to check permissions
    participant = await service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant")

    # Check permission to edit this participant
    permissions.can_edit_participant(current_user, participant)

    # Validate participant is eligible for invitation resend
    if participant.role not in ['invitee', 'sponsor']:
        raise bad_request(f"Cannot resend invitation to {participant.role} role. Only invitees and sponsors can receive invitations.")

    # Check EventParticipation status for current event
    from app.models.event import ParticipationStatus
    participation = await participant.get_current_event_participation(db)
    if participation and participation.status == ParticipationStatus.CONFIRMED.value:
        raise bad_request("Participant has already confirmed for current event. Cannot resend invitation to confirmed users.")

    if not participant.is_active:
        raise bad_request("Cannot resend invitation to inactive participant.")

    # Get active event for email context
    from app.models.event import Event
    event_result = await db.execute(
        select(Event).where(Event.is_active == True)
    )
    event = event_result.scalar_one_or_none()

    if not event:
        raise bad_request("No active event found. Cannot resend invitation without an active event.")

    # Queue invitation email with force=True to bypass 24-hour duplicate check
    from app.services.email_service import queue_invitation_email_for_user
    try:
        queue_entry = await queue_invitation_email_for_user(
            user=participant,
            event=event,
            session=db,
            force=True  # Bypass 24-hour duplicate check for resends
        )
        await db.commit()

        logger.info(
            f"Resent invitation to participant {participant_id} ({participant.email}) "
            f"by user {current_user.id} ({current_user.email}) [queue_id: {queue_entry.id}]"
        )
    except Exception as e:
        logger.error(f"Failed to queue resend invitation for participant {participant_id}: {str(e)}")
        raise server_error(f"Failed to queue invitation email: {str(e)}")

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    audit_service = AuditService(db)
    await audit_service.log(
        action="RESEND_INVITATION",
        user_id=current_user.id,
        resource_type="USER",
        resource_id=participant_id,
        details={
            "target_user_id": participant_id,
            "target_email": participant.email,
            "event_id": event.id,
            "event_name": event.name
        },
        ip_address=ip_address,
        user_agent=user_agent
    )

    return {
        "success": True,
        "message": f"Invitation email queued for {participant.email}",
        "queue_id": queue_entry.id,
        "confirmation_code_updated": True
    }


@router.post("/participants/{participant_id}/reset-workflow")
async def reset_participant_workflow(
    participant_id: int,
    reset_event_participation: bool = True,
    request: Request = None,
    current_user: User = Depends(get_current_admin_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Reset workflow state for a participant.

    This endpoint resets all workflow-related fields including:
    - Confirmation code and timestamps
    - Confirmed status (back to UNKNOWN)
    - Terms acceptance
    - All reminder timestamps
    - Password email timestamp
    - EventParticipation record for current event (optional)

    Useful for:
    - Testing invitation flows
    - Re-inviting users for new event years
    - Recovering from workflow errors

    Requires admin role.
    """
    # Get the participant first
    participant = await service.get_participant(participant_id)
    if not participant:
        raise not_found("Participant")

    # Reset workflow state
    participant = await service.reset_workflow_state(
        participant_id=participant_id,
        reset_event_participation=reset_event_participation
    )

    # Audit log
    from app.api.utils.request import extract_client_metadata
    audit_service = AuditService(db)
    ip_address, user_agent = extract_client_metadata(request)

    await audit_service.log(
        action="RESET_WORKFLOW",
        user_id=current_user.id,
        resource_type="USER",
        resource_id=participant_id,
        details={
            "target_user_id": participant_id,
            "target_email": participant.email,
            "reset_event_participation": reset_event_participation
        },
        ip_address=ip_address,
        user_agent=user_agent
    )

    return {
        "success": True,
        "message": f"Workflow state reset for {participant.email}",
        "new_confirmation_code": participant.confirmation_code,
        "reset_event_participation": reset_event_participation
    }


# ============== Admin-only Role and Sponsor Management ==============

@router.get("/sponsors", response_model=List[ParticipantResponse])
async def list_sponsors(
    current_user: User = Depends(get_current_admin_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    List all users who can be sponsors (admins and sponsors).

    Requires admin role.
    """
    sponsors = await service.list_sponsors()
    items = []
    for s in sponsors:
        item = await build_participant_response(s, db)
        items.append(item)
    return items


@router.put("/participants/{participant_id}/role")
async def update_participant_role(
    participant_id: int,
    data: RoleUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_admin_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a participant's role.

    Requires admin role.
    """
    if data.participant_id != participant_id:
        raise bad_request("Participant ID in URL does not match request body")

    # Get current role before updating
    old_participant = await service.get_participant(participant_id)
    if not old_participant:
        raise not_found("Participant")
    old_role = old_participant.role

    participant = await service.update_role(participant_id, data.role.value)
    if not participant:
        raise not_found("Participant")

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    audit_service = AuditService(db)
    await audit_service.log_role_change(
        user_id=current_user.id,
        target_user_id=participant_id,
        old_role=old_role,
        new_role=data.role.value,
        ip_address=ip_address,
        user_agent=user_agent
    )

    return await build_participant_response(participant, db)


@router.put("/participants/{participant_id}/sponsor")
async def assign_participant_sponsor(
    participant_id: int,
    data: SponsorAssignRequest,
    current_user: User = Depends(get_current_admin_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Assign a sponsor to a participant.

    Requires admin role.
    """
    if data.participant_id != participant_id:
        raise bad_request("Participant ID in URL does not match request body")

    # Verify sponsor exists and has appropriate role
    sponsor = await service.get_sponsor(data.sponsor_id)
    if not sponsor:
        raise bad_request("Invalid sponsor ID. User must have admin or sponsor role.")

    participant = await service.assign_sponsor(participant_id, data.sponsor_id)
    if not participant:
        raise not_found("Participant")

    return await build_participant_response(participant, db)


# ============== Sponsor's Own Participants ==============

@router.get("/my-participants", response_model=MySponsoredParticipantsResponse)
async def get_my_sponsored_participants(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service),
    db: AsyncSession = Depends(get_db)
):
    """
    Get participants sponsored by the current user.

    For sponsors to view only their sponsored participants.
    """
    participants, total = await service.get_sponsored_participants(
        sponsor_id=current_user.id,
        page=page,
        page_size=page_size
    )

    items = []
    for p in participants:
        item = await build_participant_response(p, db)
        items.append(item)

    return MySponsoredParticipantsResponse(
        items=items,
        total=total
    )


# ============== Audit Log Viewing ==============

@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List audit logs with filtering and pagination.

    Requires admin role.
    """
    # Build base query
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    count_query = select(func.count(AuditLog.id))

    # Apply filters
    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)

    if user_id:
        query = query.where(AuditLog.user_id == user_id)
        count_query = count_query.where(AuditLog.user_id == user_id)

    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
        count_query = count_query.where(AuditLog.resource_type == resource_type)

    if start_date:
        query = query.where(AuditLog.created_at >= start_date)
        count_query = count_query.where(AuditLog.created_at >= start_date)

    if end_date:
        query = query.where(AuditLog.created_at <= end_date)
        count_query = count_query.where(AuditLog.created_at <= end_date)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Apply pagination
    offset, _ = calculate_pagination(total, page, page_size)
    query = query.offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    audit_logs = result.scalars().all()

    # Build responses with user info
    items = []
    for log in audit_logs:
        # Get user info if user_id exists
        user_email = None
        user_name = None
        if log.user_id:
            user_result = await db.execute(
                select(User).where(User.id == log.user_id)
            )
            user = user_result.scalar_one_or_none()
            if user:
                user_email = user.email
                user_name = f"{user.first_name} {user.last_name}"

        item = AuditLogResponse(
            id=log.id,
            user_id=log.user_id,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            details=log.details,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            created_at=log.created_at,
            user_email=user_email,
            user_name=user_name
        )
        items.append(item)

    _, total_pages = calculate_pagination(total, page, page_size)

    return AuditLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/audit-logs/stats", response_model=AuditLogStats)
async def get_audit_log_stats(
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get audit log statistics.

    Requires admin role.
    """
    # Total events
    total_result = await db.execute(select(func.count(AuditLog.id)))
    total_events = total_result.scalar() or 0

    # Count by action type
    login_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "LOGIN_SUCCESS")
    )
    login_count = login_result.scalar() or 0

    logout_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "LOGOUT")
    )
    logout_count = logout_result.scalar() or 0

    user_create_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "USER_CREATE")
    )
    user_create_count = user_create_result.scalar() or 0

    user_update_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "USER_UPDATE")
    )
    user_update_count = user_update_result.scalar() or 0

    user_delete_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "USER_DELETE")
    )
    user_delete_count = user_delete_result.scalar() or 0

    role_change_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "ROLE_CHANGE")
    )
    role_change_count = role_change_result.scalar() or 0

    password_reset_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "PASSWORD_RESET")
    )
    password_reset_count = password_reset_result.scalar() or 0

    # VPN request statistics
    vpn_success_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "VPN_REQUEST_SUCCESS")
    )
    vpn_request_success_count = vpn_success_result.scalar() or 0

    vpn_failed_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "VPN_REQUEST_FAILED")
    )
    vpn_request_failed_count = vpn_failed_result.scalar() or 0

    vpn_rate_limited_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "VPN_REQUEST_RATE_LIMITED")
    )
    vpn_request_rate_limited_count = vpn_rate_limited_result.scalar() or 0

    # Recent 24h
    twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.created_at >= twenty_four_hours_ago)
    )
    recent_24h = recent_result.scalar() or 0

    return AuditLogStats(
        total_events=total_events,
        login_count=login_count,
        logout_count=logout_count,
        user_create_count=user_create_count,
        user_update_count=user_update_count,
        user_delete_count=user_delete_count,
        role_change_count=role_change_count,
        password_reset_count=password_reset_count,
        vpn_request_success_count=vpn_request_success_count,
        vpn_request_failed_count=vpn_request_failed_count,
        vpn_request_rate_limited_count=vpn_request_rate_limited_count,
        recent_24h=recent_24h
    )


# ============== Email Queue Management ==============

@router.get("/email-queue")
async def list_email_queue(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    exclude_status: Optional[str] = Query(None, description="Exclude specific status"),
    since: Optional[str] = Query(None, description="Filter by created/updated since (ISO datetime)"),
    template_name: Optional[str] = Query(None, description="Filter by template"),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List email queue items with filtering and pagination.

    Requires admin role.
    """
    from datetime import datetime
    from sqlalchemy import or_

    # Build query
    query = select(EmailQueue).order_by(
        EmailQueue.priority.asc(),
        EmailQueue.created_at.asc()
    )
    count_query = select(func.count(EmailQueue.id))

    # Apply filters
    if status:
        query = query.where(EmailQueue.status == status)
        count_query = count_query.where(EmailQueue.status == status)

    if exclude_status:
        query = query.where(EmailQueue.status != exclude_status)
        count_query = count_query.where(EmailQueue.status != exclude_status)

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            query = query.where(EmailQueue.created_at >= since_dt)
            count_query = count_query.where(EmailQueue.created_at >= since_dt)
        except ValueError:
            pass  # Ignore invalid datetime

    if template_name:
        query = query.where(EmailQueue.template_name == template_name)
        count_query = count_query.where(EmailQueue.template_name == template_name)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset, total_pages = calculate_pagination(total, page, page_size)
    query = query.offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    queue_items = result.scalars().all()

    # Build response
    items = []
    for item in queue_items:
        items.append({
            "id": item.id,
            "user_id": item.user_id,
            "template_name": item.template_name,
            "recipient_email": item.recipient_email,
            "recipient_name": item.recipient_name,
            "priority": item.priority,
            "status": item.status,
            "attempts": item.attempts,
            "max_attempts": item.max_attempts,
            "created_at": item.created_at,
            "scheduled_for": item.scheduled_for,
            "sent_at": item.sent_at,
            "processed_at": item.processed_at,
            "batch_id": item.batch_id,
            "processed_by": item.processed_by,
            "error_message": item.error_message
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@router.get("/email-queue/stats")
async def get_email_queue_stats(
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get email queue statistics.

    Requires admin role.
    """
    queue_service = EmailQueueService(db)
    stats = await queue_service.get_queue_stats()

    return stats


@router.post("/email-queue/process-batch")
async def process_email_batch_manually(
    batch_size: int = Query(50, ge=1, le=100, description="Batch size"),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger batch email processing.

    Requires admin role.
    """
    queue_service = EmailQueueService(db)

    batch_log = await queue_service.process_batch(
        batch_size=batch_size,
        worker_id=f"manual_{current_user.id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    )

    return {
        "success": True,
        "batch_id": batch_log.batch_id,
        "total_sent": batch_log.total_sent,
        "total_failed": batch_log.total_failed,
        "duration_seconds": batch_log.duration_seconds
    }


@router.delete("/email-queue/{email_id}")
async def cancel_queued_email(
    email_id: int,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel a pending email in the queue.

    Requires admin role.
    """
    queue_service = EmailQueueService(db)
    success = await queue_service.cancel_email(email_id)

    if not success:
        raise not_found("Email", email_id)

    return {"success": True, "message": "Email cancelled successfully"}


@router.get("/email-batch-logs")
async def list_email_batch_logs(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List email batch processing logs.

    Requires admin role.
    """
    # Build query
    query = select(EmailBatchLog).order_by(EmailBatchLog.started_at.desc())

    # Get total count
    count_result = await db.execute(select(func.count(EmailBatchLog.id)))
    total = count_result.scalar() or 0

    # Apply pagination
    offset, total_pages = calculate_pagination(total, page, page_size)
    query = query.offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    batch_logs = result.scalars().all()

    # Build response
    items = []
    for log in batch_logs:
        items.append({
            "id": log.id,
            "batch_id": log.batch_id,
            "batch_size": log.batch_size,
            "total_processed": log.total_processed,
            "total_sent": log.total_sent,
            "total_failed": log.total_failed,
            "started_at": log.started_at,
            "completed_at": log.completed_at,
            "duration_seconds": log.duration_seconds,
            "processed_by": log.processed_by,
            "error_message": log.error_message
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


# ============== Scheduler Management ==============

@router.get("/scheduler/jobs")
async def list_scheduler_jobs(
    current_user: User = Depends(get_current_admin_user)
):
    """
    List all scheduled jobs with their next run times.

    Requires admin role.
    """
    from app.tasks.scheduler import list_jobs

    jobs = list_jobs()

    return {
        "jobs": jobs,
        "total": len(jobs)
    }


@router.get("/scheduler/status")
async def get_scheduler_status(
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get overall scheduler health and status from background worker.

    Requires admin role.

    The background worker updates its status in the database every 60 seconds.
    This endpoint reads that status.
    """
    from app.models.scheduler_status import SchedulerStatus
    from datetime import datetime, timezone, timedelta

    # Get latest status from database
    result = await db.execute(
        select(SchedulerStatus).where(SchedulerStatus.service_name == "web-service")
    )
    status = result.scalar_one_or_none()

    if not status:
        # Scheduler hasn't started yet or hasn't written status
        return {
            "running": False,
            "total_jobs": 0,
            "jobs": [],
            "last_heartbeat": None,
            "healthy": False,
            "message": "Scheduler has not reported status yet. It may still be starting up."
        }

    # Check if heartbeat is recent (within last 2 minutes)
    now = datetime.now(timezone.utc)
    heartbeat_age = now - status.last_heartbeat
    is_healthy = heartbeat_age < timedelta(minutes=2)

    return {
        "running": status.is_running,
        "total_jobs": len(status.jobs),
        "jobs": status.jobs,
        "last_heartbeat": status.last_heartbeat.isoformat(),
        "heartbeat_age_seconds": heartbeat_age.total_seconds(),
        "healthy": is_healthy,
        "message": "Healthy" if is_healthy else f"Warning: Last heartbeat was {int(heartbeat_age.total_seconds())} seconds ago"
    }


# =============================================================================
# Event Lifecycle Management Endpoints
# =============================================================================

@router.get("/event/current")
async def get_current_event(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Get current event configuration."""
    from app.services.event_service import EventService

    event_service = EventService(db)
    event = await event_service.get_current_event()

    if not event:
        return {"event": None}

    return {"event": _build_event_dict(event)}


@router.post("/event/toggle-active")
async def toggle_event_active(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Toggle event active status - ADMIN ONLY."""
    from app.services.event_service import EventService

    if current_user.role != UserRole.ADMIN.value:
        raise forbidden("Only administrators can toggle event status")

    event_service = EventService(db)
    event = await event_service.get_current_event()

    if not event:
        raise not_found("No event configured")

    event.is_active = not event.is_active
    await db.commit()

    return {
        "success": True,
        "is_active": event.is_active,
        "message": f"Event {'activated' if event.is_active else 'deactivated'}"
    }


def _build_event_dict(event):
    """Helper to build event response dictionary."""
    return {
        "id": event.id,
        "year": event.year,
        "name": event.name,
        "is_active": event.is_active,
        "is_archived": event.is_archived,
        "registration_open": event.registration_open,
        "registration_opens": event.registration_opens.isoformat() if event.registration_opens else None,
        "registration_closes": event.registration_closes.isoformat() if event.registration_closes else None,
        "vpn_available": event.vpn_available,
        "test_mode": event.test_mode,
        "start_date": event.start_date.isoformat() if event.start_date else None,
        "end_date": event.end_date.isoformat() if event.end_date else None,
        "event_time": event.event_time,
        "event_location": event.event_location,
        "terms_version": event.terms_version,
        "terms_content": event.terms_content,
        "max_participants": event.max_participants,
        "confirmation_expires_days": event.confirmation_expires_days,
        "ssh_public_key": event.ssh_public_key,
        "ssh_private_key": event.ssh_private_key,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None
    }


@router.get("/events")
async def list_events(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
    include_archived: bool = Query(False, description="Include archived events")
):
    """List all events."""
    from app.services.event_service import EventService

    service = EventService(db)
    events = await service.list_events(include_archived=include_archived)

    return {
        "events": [_build_event_dict(event) for event in events]
    }


@router.post("/events")
async def create_event(
    data: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Create a new event."""
    from app.services.event_service import EventService
    from datetime import datetime as dt

    if current_user.role != UserRole.ADMIN.value:
        raise forbidden("Only administrators can create events")

    service = EventService(db)

    # Check if event for this year already exists
    existing = await service.get_event_by_year(data.get("year"))
    if existing:
        raise bad_request(f"Event for year {data.get('year')} already exists")

    # Parse dates if provided
    start_date = None
    end_date = None
    if data.get("start_date"):
        start_date = dt.fromisoformat(data["start_date"].replace("Z", "+00:00")).date()
    if data.get("end_date"):
        end_date = dt.fromisoformat(data["end_date"].replace("Z", "+00:00")).date()

    # Create event using service
    event = await service.create_event(
        year=data["year"],
        name=data["name"],
        start_date=start_date,
        end_date=end_date,
        event_time=data.get("event_time"),
        event_location=data.get("event_location"),
        is_active=data.get("is_active", False),
        registration_open=data.get("registration_open", False),
        terms_version=data.get("terms_version"),
        terms_content=data.get("terms_content"),
        max_participants=data.get("max_participants"),
        confirmation_expires_days=data.get("confirmation_expires_days", 30)
    )

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    audit_service = AuditService(db)
    await audit_service.log_event_create(
        user_id=current_user.id,
        event_id=event.id,
        details={"year": event.year, "name": event.name},
        ip_address=ip_address,
        user_agent=user_agent
    )

    return {
        "success": True,
        "event": {
            "id": event.id,
            "year": event.year,
            "name": event.name
        }
    }


@router.get("/events/{event_id}")
async def get_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Get event details."""
    from app.services.event_service import EventService

    service = EventService(db)
    event = await service.get_event(event_id)

    if not event:
        raise not_found("Event")

    return {"event": _build_event_dict(event)}


@router.put("/events/{event_id}")
async def update_event(
    event_id: int,
    data: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Update event details."""
    from app.services.event_service import EventService
    from datetime import datetime as dt

    if current_user.role != UserRole.ADMIN.value:
        raise forbidden("Only administrators can update events")

    service = EventService(db)
    event = await service.get_event(event_id)

    if not event:
        raise not_found("Event")

    # Track changes for audit and workflow triggers
    changes = {}
    update_data = {}

    # Helper to make values JSON-serializable
    def make_json_serializable(value):
        """Convert Python objects to JSON-serializable format."""
        if value is None:
            return None
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    # Helper to track and stage field updates
    def track_field(field_name, new_value, parse_fn=None):
        old_value = getattr(event, field_name)
        parsed_value = parse_fn(new_value) if parse_fn and new_value else new_value
        if parsed_value != old_value:
            # For audit log display (strings)
            old_str = str(old_value) if old_value is not None else None
            new_str = str(parsed_value) if parsed_value is not None else None
            if field_name == "terms_content":
                changes[field_name] = {"old": "...", "new": "...", "old_value": "...", "new_value": "..."}
            else:
                # Store both string (for audit) and actual value (for trigger checks)
                # Ensure values are JSON-serializable
                changes[field_name] = {
                    "old": old_str,
                    "new": new_str,
                    "old_value": make_json_serializable(old_value),
                    "new_value": make_json_serializable(parsed_value)
                }
            update_data[field_name] = parsed_value

    # Date parser
    def parse_date(date_str):
        return dt.fromisoformat(date_str.replace("Z", "+00:00")).date() if date_str else None

    # Track all potential field updates
    if "name" in data:
        track_field("name", data["name"])
    if "start_date" in data:
        track_field("start_date", data["start_date"], parse_date)
    if "end_date" in data:
        track_field("end_date", data["end_date"], parse_date)
    if "event_time" in data:
        track_field("event_time", data["event_time"])
    if "event_location" in data:
        track_field("event_location", data["event_location"])
    if "registration_open" in data:
        track_field("registration_open", data["registration_open"])
    if "vpn_available" in data:
        track_field("vpn_available", data["vpn_available"])
    if "test_mode" in data:
        track_field("test_mode", data["test_mode"])
    if "terms_content" in data:
        track_field("terms_content", data["terms_content"])
    if "terms_version" in data:
        track_field("terms_version", data["terms_version"])
    if "max_participants" in data:
        track_field("max_participants", data["max_participants"])
    if "confirmation_expires_days" in data:
        track_field("confirmation_expires_days", data["confirmation_expires_days"])
    if "ssh_public_key" in data:
        track_field("ssh_public_key", data["ssh_public_key"])
    if "ssh_private_key" in data:
        track_field("ssh_private_key", data["ssh_private_key"])

    # Handle is_active separately (requires deactivating other events)
    if "is_active" in data and data["is_active"] != event.is_active:
        old_is_active = event.is_active
        new_is_active = data["is_active"]
        # Store both string (for audit) and actual value (for trigger checks)
        changes["is_active"] = {
            "old": str(old_is_active),
            "new": str(new_is_active),
            "old_value": make_json_serializable(old_is_active),
            "new_value": make_json_serializable(new_is_active)
        }
        if data["is_active"]:
            await service.deactivate_other_events(except_event_id=event_id)
        update_data["is_active"] = data["is_active"]

    # Apply all updates using service
    if update_data:
        event = await service.update_event(event_id, **update_data)

    # Check what changed that could trigger invitation workflow
    # Use old_value/new_value (actual types) instead of old/new (strings)
    became_active = changes.get("is_active", {}).get("new_value") is True and changes.get("is_active", {}).get("old_value") is False
    entered_test_mode = changes.get("test_mode", {}).get("new_value") is True and changes.get("test_mode", {}).get("old_value") is False
    exited_test_mode = changes.get("test_mode", {}).get("old_value") is True and changes.get("test_mode", {}).get("new_value") is False
    registration_opened = changes.get("registration_open", {}).get("new_value") is True and changes.get("registration_open", {}).get("old_value") is False

    logger.info(
        f"Event {event_id} update check: "
        f"became_active={became_active}, entered_test_mode={entered_test_mode}, "
        f"exited_test_mode={exited_test_mode}, registration_opened={registration_opened}, "
        f"is_active={event.is_active}, changes={list(changes.keys())}"
    )

    # Trigger invitation workflow if:
    # 1. Event became active (naturally active now)
    # 2. Event entered test mode AND is active
    # 3. Registration opened AND event is active
    # 4. Test mode was disabled AND event is active AND registration is open
    should_trigger = (
        became_active or
        (entered_test_mode and event.is_active) or
        (registration_opened and event.is_active) or
        (exited_test_mode and event.is_active and event.registration_open)
    )

    if should_trigger:
        logger.info(
            f"Triggering invitation email workflow for event {event.name} (ID: {event.id}) "
            f"[became_active={became_active}, entered_test_mode={entered_test_mode}, "
            f"exited_test_mode={exited_test_mode}, registration_opened={registration_opened}, "
            f"test_mode={event.test_mode}]"
        )
        from app.tasks.invitation_emails import schedule_invitation_emails
        schedule_invitation_emails(event.id, event.name, test_mode=event.test_mode)
        logger.info(
            f"Invitation email workflow scheduled for event {event.name} "
            f"[test_mode={event.test_mode}]"
        )

    # Audit log
    if changes:
        ip_address, user_agent = extract_client_metadata(request)
        audit_service = AuditService(db)
        await audit_service.log_event_update(
            user_id=current_user.id,
            event_id=event.id,
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent
        )

    return {"success": True, "message": "Event updated successfully"}


@router.post("/events/{event_id}/activate")
async def activate_event(
    event_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Set an event as the active event (deactivates all others)."""
    from app.services.event_service import EventService

    if current_user.role != UserRole.ADMIN.value:
        raise forbidden("Only administrators can activate events")

    service = EventService(db)
    event = await service.get_event(event_id)

    if not event:
        raise not_found("Event")

    if event.is_archived:
        raise bad_request("Cannot activate an archived event")

    # Deactivate all other events and activate this one
    await service.deactivate_other_events(except_event_id=event_id)
    event = await service.update_event(event_id, is_active=True)

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    audit_service = AuditService(db)
    await audit_service.log_event_activate(
        user_id=current_user.id,
        event_id=event.id,
        ip_address=ip_address,
        user_agent=user_agent
    )

    return {"success": True, "message": f"Event {event.year} activated"}


@router.post("/events/{event_id}/archive")
async def archive_event(
    event_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Archive an event."""
    from app.services.event_service import EventService

    if current_user.role != UserRole.ADMIN.value:
        raise forbidden("Only administrators can archive events")

    service = EventService(db)
    event = await service.get_event(event_id)

    if not event:
        raise not_found("Event")

    if event.is_active:
        raise bad_request("Cannot archive the active event. Deactivate it first.")

    event = await service.update_event(event_id, is_archived=True)

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    audit_service = AuditService(db)
    await audit_service.log_event_archive(
        user_id=current_user.id,
        event_id=event.id,
        ip_address=ip_address,
        user_agent=user_agent
    )

    return {"success": True, "message": f"Event {event.year} archived"}


# =============================================================================
# Email Workflow Management Endpoints
# =============================================================================

@router.get("/email-workflows")
async def list_workflows(
    enabled_only: bool = False,
    trigger_event: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all email workflows (admin only).

    Query Parameters:
    - enabled_only: Only return enabled workflows
    - trigger_event: Filter by trigger event
    - page: Page number
    - page_size: Items per page
    """
    from app.models.email_workflow import EmailWorkflow

    # Build query
    query = select(EmailWorkflow)

    if enabled_only:
        query = query.where(EmailWorkflow.is_enabled == True)

    if trigger_event:
        query = query.where(EmailWorkflow.trigger_event == trigger_event)

    query = query.order_by(EmailWorkflow.created_at.desc())

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Apply pagination
    offset, total_pages = calculate_pagination(total, page, page_size)
    query = query.offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    workflows = result.scalars().all()

    # Build response
    from app.schemas.workflow import WorkflowResponse
    items = [WorkflowResponse.model_validate(wf) for wf in workflows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@router.get("/email-workflows/trigger-events")
async def get_trigger_events(
    current_user: User = Depends(get_current_admin_user)
):
    """Get available trigger events and their metadata."""
    from app.models.email_workflow import WorkflowTriggerEvent

    events = [
        {
            "event": WorkflowTriggerEvent.USER_CREATED,
            "display_name": "User Created",
            "description": "Triggered when a new user is created",
            "available_variables": ["first_name", "last_name", "email", "login_url"]
        },
        {
            "event": WorkflowTriggerEvent.USER_CONFIRMED,
            "display_name": "User Confirmed",
            "description": "Triggered when a user confirms participation",
            "available_variables": ["first_name", "last_name", "email", "login_url", "event_name"]
        },
        {
            "event": WorkflowTriggerEvent.VPN_ASSIGNED,
            "display_name": "VPN Assigned",
            "description": "Triggered when VPN credentials are assigned",
            "available_variables": ["first_name", "last_name", "email", "pandas_username", "pandas_password"]
        },
        {
            "event": WorkflowTriggerEvent.EVENT_REMINDER_1,
            "display_name": "Invitation Reminder — Stage 1",
            "description": "First follow-up sent ~7 days after initial invitation",
            "available_variables": ["first_name", "last_name", "email", "event_name", "event_date_range", "event_time", "event_location", "event_start_date", "days_until_event", "confirmation_url", "reminder_stage"]
        },
        {
            "event": WorkflowTriggerEvent.EVENT_REMINDER_2,
            "display_name": "Invitation Reminder — Stage 2",
            "description": "Second follow-up sent ~14 days after initial invitation",
            "available_variables": ["first_name", "last_name", "email", "event_name", "event_date_range", "event_time", "event_location", "event_start_date", "days_until_event", "confirmation_url", "reminder_stage"]
        },
        {
            "event": WorkflowTriggerEvent.EVENT_REMINDER_FINAL,
            "display_name": "Invitation Reminder — Final",
            "description": "Last-chance reminder sent ~3 days before event starts",
            "available_variables": ["first_name", "last_name", "email", "event_name", "event_date_range", "event_time", "event_location", "event_start_date", "days_until_event", "confirmation_url", "reminder_stage", "is_final_reminder"]
        },
        {
            "event": WorkflowTriggerEvent.SURVEY_REQUEST,
            "display_name": "Survey Request",
            "description": "Triggered after event completion for feedback",
            "available_variables": ["first_name", "last_name", "email", "survey_url"]
        },
        {
            "event": WorkflowTriggerEvent.PASSWORD_RESET,
            "display_name": "Password Reset",
            "description": "Triggered when password is reset",
            "available_variables": ["first_name", "last_name", "email", "reset_url"]
        }
    ]

    return {"events": events}


@router.get("/email-workflows/{workflow_id}")
async def get_workflow(
    workflow_id: int,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a single workflow by ID."""
    from app.models.email_workflow import EmailWorkflow
    from app.schemas.workflow import WorkflowResponse

    result = await db.execute(
        select(EmailWorkflow).where(EmailWorkflow.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise not_found("Workflow")

    return WorkflowResponse.model_validate(workflow)


@router.post("/email-workflows")
async def create_workflow(
    workflow_data: dict,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new email workflow."""
    from app.models.email_workflow import EmailWorkflow
    from app.schemas.workflow import WorkflowCreate, WorkflowResponse

    # Validate with schema
    workflow_create = WorkflowCreate(**workflow_data)

    # Check if name already exists
    existing = await db.execute(
        select(EmailWorkflow).where(EmailWorkflow.name == workflow_create.name)
    )
    if existing.scalar_one_or_none():
        raise bad_request(f"Workflow with name '{workflow_create.name}' already exists")

    # Create workflow
    workflow = EmailWorkflow(
        name=workflow_create.name,
        display_name=workflow_create.display_name,
        description=workflow_create.description,
        trigger_event=workflow_create.trigger_event,
        template_name=workflow_create.template_name,
        priority=workflow_create.priority,
        custom_vars=workflow_create.custom_vars or {},
        delay_minutes=workflow_create.delay_minutes,
        is_enabled=workflow_create.is_enabled,
        from_email=workflow_create.from_email,
        from_name=workflow_create.from_name,
        created_by_id=current_user.id
    )

    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log_workflow_create(
        user_id=current_user.id,
        workflow_id=workflow.id,
        details={
            "name": workflow.name,
            "display_name": workflow.display_name,
            "trigger_event": workflow.trigger_event,
            "template_name": workflow.template_name,
            "priority": workflow.priority,
            "is_enabled": workflow.is_enabled
        }
    )

    return WorkflowResponse.model_validate(workflow)


@router.put("/email-workflows/{workflow_id}")
async def update_workflow(
    workflow_id: int,
    workflow_data: dict,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Update an existing workflow."""
    from app.models.email_workflow import EmailWorkflow
    from app.schemas.workflow import WorkflowUpdate, WorkflowResponse

    # Get workflow
    result = await db.execute(
        select(EmailWorkflow).where(EmailWorkflow.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise not_found("Workflow")

    # Validate with schema
    workflow_update = WorkflowUpdate(**workflow_data)

    # Track changes for audit log
    changes = {}

    # Update fields
    if workflow_update.display_name is not None:
        changes["display_name"] = {"old": workflow.display_name, "new": workflow_update.display_name}
        workflow.display_name = workflow_update.display_name
    if workflow_update.description is not None:
        changes["description"] = {"old": workflow.description, "new": workflow_update.description}
        workflow.description = workflow_update.description
    if workflow_update.trigger_event is not None:
        changes["trigger_event"] = {"old": workflow.trigger_event, "new": workflow_update.trigger_event}
        workflow.trigger_event = workflow_update.trigger_event
    if workflow_update.template_name is not None:
        changes["template_name"] = {"old": workflow.template_name, "new": workflow_update.template_name}
        workflow.template_name = workflow_update.template_name
    if workflow_update.priority is not None:
        changes["priority"] = {"old": workflow.priority, "new": workflow_update.priority}
        workflow.priority = workflow_update.priority
    if workflow_update.custom_vars is not None:
        changes["custom_vars"] = {"old": workflow.custom_vars, "new": workflow_update.custom_vars}
        workflow.custom_vars = workflow_update.custom_vars
    if workflow_update.delay_minutes is not None:
        changes["delay_minutes"] = {"old": workflow.delay_minutes, "new": workflow_update.delay_minutes}
        workflow.delay_minutes = workflow_update.delay_minutes
    if workflow_update.is_enabled is not None:
        changes["is_enabled"] = {"old": workflow.is_enabled, "new": workflow_update.is_enabled}
        workflow.is_enabled = workflow_update.is_enabled
    if workflow_update.from_email is not None:
        changes["from_email"] = {"old": workflow.from_email, "new": workflow_update.from_email}
        workflow.from_email = workflow_update.from_email or None  # empty string → NULL
    if workflow_update.from_name is not None:
        changes["from_name"] = {"old": workflow.from_name, "new": workflow_update.from_name}
        workflow.from_name = workflow_update.from_name or None  # empty string → NULL

    await db.commit()
    await db.refresh(workflow)

    # Audit log
    if changes:
        audit_service = AuditService(db)
        await audit_service.log_workflow_update(
            user_id=current_user.id,
            workflow_id=workflow.id,
            changes=changes
        )

    return WorkflowResponse.model_validate(workflow)


@router.delete("/email-workflows/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a workflow (system workflows cannot be deleted)."""
    from app.models.email_workflow import EmailWorkflow

    # Get workflow
    result = await db.execute(
        select(EmailWorkflow).where(EmailWorkflow.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise not_found("Workflow")

    if workflow.is_system:
        raise bad_request("Cannot delete system workflows")

    # Audit log (before deletion)
    audit_service = AuditService(db)
    await audit_service.log_workflow_delete(
        user_id=current_user.id,
        workflow_id=workflow.id,
        details={
            "name": workflow.name,
            "display_name": workflow.display_name,
            "trigger_event": workflow.trigger_event,
            "template_name": workflow.template_name
        }
    )

    await db.delete(workflow)
    await db.commit()

    return {"success": True, "message": "Workflow deleted successfully"}
