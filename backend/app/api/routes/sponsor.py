"""Sponsor-specific routes for managing invitees."""
import logging
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.exceptions import not_found, forbidden, bad_request, conflict, unauthorized, server_error
from app.dependencies import get_db, get_current_sponsor_user, PermissionChecker
from app.api.utils.request import extract_client_metadata
from app.api.utils.pagination import calculate_pagination
from app.api.utils.dependencies import get_participant_service
from app.models.user import User
from app.services.participant_service import ParticipantService
from app.schemas.participant import (
    ParticipantResponse,
    SponsorInviteeListResponse,
    SponsorInviteeStats,
    InviteeCreateRequest,
    InviteeUpdateRequest
)
from app.api.utils.response_builders import build_participant_response


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sponsors", tags=["sponsors"])


@router.get("/my-invitees", response_model=SponsorInviteeListResponse)
async def list_my_invitees(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    confirmed: Optional[str] = None,
    has_vpn: Optional[bool] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service)
):
    """
    List all invitees sponsored by the current user.

    Supports pagination, search, and filtering.
    """
    logger.info(f"Sponsor {current_user.id} listing invitees (page={page}, search={search})")

    # Auto-filter by sponsor_id - sponsors can only see their own invitees
    participants, total = await service.list_participants(
        sponsor_id=current_user.id,  # Critical: enforce data isolation
        page=page,
        page_size=page_size,
        search=search,
        confirmed=confirmed,
        has_vpn=has_vpn,
        is_active=is_active
    )

    # Build responses
    items = [await build_participant_response(p, db) for p in participants]

    _, total_pages = calculate_pagination(total, page, page_size)

    return SponsorInviteeListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/my-invitees/stats", response_model=SponsorInviteeStats)
async def get_my_invitees_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service)
):
    """
    Get statistics for the current sponsor's invitees.
    """
    logger.info(f"Sponsor {current_user.id} fetching invitee statistics")

    # Get stats filtered by sponsor_id
    stats = await service.get_statistics(sponsor_id=current_user.id)

    return SponsorInviteeStats(
        total_invitees=stats.get("total", 0),
        confirmed_count=stats.get("confirmed", 0),
        unconfirmed_count=stats.get("unconfirmed", 0),
        with_vpn_count=stats.get("with_vpn", 0),
        without_vpn_count=stats.get("without_vpn", 0),
        active_count=stats.get("active", 0),
        inactive_count=stats.get("inactive", 0)
    )


@router.get("/my-invitees/{invitee_id}", response_model=ParticipantResponse)
async def get_my_invitee(
    invitee_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service)
):
    """
    Get details for a specific invitee.

    Only returns the invitee if sponsored by the current user.
    """
    logger.info(f"Sponsor {current_user.id} fetching invitee {invitee_id}")
    invitee = await service.get_participant(invitee_id)

    # Verify ownership - critical security check
    if not invitee or invitee.sponsor_id != current_user.id:
        logger.warning(
            f"Sponsor {current_user.id} attempted to access invitee {invitee_id} "
            f"(not their invitee)"
        )
        raise not_found("Invitee not found")

    return await build_participant_response(invitee, db)


@router.post("/my-invitees", response_model=ParticipantResponse)
async def create_my_invitee(
    request: Request,
    data: InviteeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service)
):
    """
    Create a new invitee with the current user as sponsor.

    The sponsor_id is automatically set to the current user.
    """
    logger.info(
        f"Sponsor {current_user.id} creating invitee: {data.first_name} {data.last_name} "
        f"({data.email})"
    )

    # Create invitee with auto-assigned sponsor_id
    invitee = await service.create_participant(
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
        country=data.country,
        role="invitee",  # Always create as invitee
        sponsor_id=current_user.id,  # Auto-assign current sponsor
        confirmed=data.confirmed,
        discord_username=data.discord_username
    )

    # Reload with relationships
    invitee = await service.get_participant(invitee.id)

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    from app.services.audit_service import AuditService
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="CREATE_INVITEE",
        resource_type="USER",
        resource_id=invitee.id,
        details={
            "invitee_email": data.email,
            "invitee_name": f"{data.first_name} {data.last_name}",
            "sponsor_id": current_user.id
        },
        ip_address=ip_address,
        user_agent=user_agent
    )

    logger.info(f"Sponsor {current_user.id} created invitee {invitee.id}")

    # Check if there's an active event and queue invitation email
    from app.services.event_service import EventService
    event_service = EventService(db)
    active_event = await event_service.get_active_event()

    if active_event and invitee.confirmed == 'UNKNOWN':
        # Queue invitation email using helper function
        from app.services.email_service import queue_invitation_email_for_user

        await queue_invitation_email_for_user(
            user=invitee,
            event=active_event,
            session=db,
            force=False
        )
        await db.commit()

        logger.info(f"Queued invitation email for new invitee {invitee.id}")

    return await build_participant_response(invitee, db)


@router.put("/my-invitees/{invitee_id}", response_model=ParticipantResponse)
async def update_my_invitee(
    invitee_id: int,
    request: Request,
    data: InviteeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service)
):
    """
    Update an invitee's information.

    Sponsors can only update limited fields:
    - email, first_name, last_name, country, confirmed, discord_username

    Cannot update: role, sponsor_id, pandas_username, is_admin, email_status
    """
    logger.info(f"Sponsor {current_user.id} updating invitee {invitee_id}")

    permissions = PermissionChecker()

    # Get and verify ownership
    invitee = await service.get_participant(invitee_id)
    if not invitee or invitee.sponsor_id != current_user.id:
        logger.warning(
            f"Sponsor {current_user.id} attempted to update invitee {invitee_id} "
            f"(not their invitee)"
        )
        raise not_found("Invitee not found")

    # Permission check
    permissions.can_edit_participant(current_user, invitee)

    # Update allowed fields only
    update_data = data.model_dump(exclude_unset=True)
    updated = await service.update_participant(invitee_id, **update_data)

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    from app.services.audit_service import AuditService
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="UPDATE_INVITEE",
        resource_type="USER",
        resource_id=invitee_id,
        details={
            "changes": update_data,
            "invitee_email": updated.email,
            "sponsor_id": current_user.id
        },
        ip_address=ip_address,
        user_agent=user_agent
    )

    logger.info(f"Sponsor {current_user.id} updated invitee {invitee_id}")

    return await build_participant_response(updated, db)


@router.delete("/my-invitees/{invitee_id}")
async def delete_my_invitee(
    invitee_id: int,
    current_user: User = Depends(get_current_sponsor_user)
):
    """
    Sponsors cannot delete invitees.

    This endpoint always returns 403 Forbidden.
    Only administrators can delete users.
    """
    logger.warning(
        f"Sponsor {current_user.id} attempted to delete invitee {invitee_id} "
        f"(not permitted)"
    )
    raise forbidden("Sponsors cannot delete invitees. Please contact an administrator.")


@router.post("/my-invitees/{invitee_id}/reset-password")
async def reset_invitee_password(
    invitee_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service)
):
    """
    Reset an invitee's password and send them an email.
    """
    logger.info(f"Sponsor {current_user.id} resetting password for invitee {invitee_id}")

    permissions = PermissionChecker()

    # Get and verify ownership
    invitee = await service.get_participant(invitee_id)
    if not invitee or invitee.sponsor_id != current_user.id:
        logger.warning(
            f"Sponsor {current_user.id} attempted to reset password for invitee {invitee_id} "
            f"(not their invitee)"
        )
        raise not_found("Invitee not found")

    # Permission check
    permissions.can_edit_participant(current_user, invitee)

    # Reset password
    success = await service.reset_password(invitee_id)

    if not success:
        raise server_error("Failed to reset password")

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    from app.services.audit_service import AuditService
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="RESET_INVITEE_PASSWORD",
        resource_type="USER",
        resource_id=invitee_id,
        details={
            "invitee_email": invitee.email,
            "sponsor_id": current_user.id
        },
        ip_address=ip_address,
        user_agent=user_agent
    )

    logger.info(f"Sponsor {current_user.id} reset password for invitee {invitee_id}")

    return {
        "success": True,
        "message": "Password reset successfully. An email has been sent to the invitee."
    }


@router.post("/my-invitees/{invitee_id}/resend-invite")
async def resend_invitee_invitation(
    invitee_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_sponsor_user),
    service: ParticipantService = Depends(get_participant_service)
):
    """
    Resend invitation email to an invitee.

    Generates a new confirmation code and bypasses 24-hour duplicate protection.
    """
    logger.info(f"Sponsor {current_user.id} resending invitation for invitee {invitee_id}")

    permissions = PermissionChecker()

    # Get and verify ownership
    invitee = await service.get_participant(invitee_id)
    if not invitee or invitee.sponsor_id != current_user.id:
        logger.warning(
            f"Sponsor {current_user.id} attempted to resend invitation for invitee {invitee_id} "
            f"(not their invitee)"
        )
        raise not_found("Invitee not found")

    # Permission check
    permissions.can_edit_participant(current_user, invitee)

    # Validate participant is eligible for invitation resend
    if invitee.role not in ['invitee', 'sponsor']:
        raise bad_request(f"Cannot resend invitation to {invitee.role} role. Only invitees and sponsors can receive invitations.")

    if invitee.confirmed == 'YES':
        raise bad_request("Participant has already confirmed. Cannot resend invitation to confirmed users.")

    if not invitee.is_active:
        raise bad_request("Cannot resend invitation to inactive participant.")

    # Check email status
    if invitee.email_status in ['BOUNCED', 'SPAM_REPORTED', 'UNSUBSCRIBED']:
        raise bad_request(f"Cannot send email: email status is {invitee.email_status}")

    # Get active event for email context
    from app.models.event import Event
    from sqlalchemy import select, update
    import secrets
    from datetime import datetime, timezone

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
            user=invitee,
            event=event,
            session=db,
            force=True  # Bypass 24-hour duplicate check for resends
        )
        await db.commit()

        logger.info(
            f"Sponsor {current_user.id} queued resend invitation for invitee {invitee_id} "
            f"({invitee.email}) [queue_id: {queue_entry.id}]"
        )
    except Exception as e:
        logger.error(f"Failed to queue resend invitation for invitee {invitee_id}: {str(e)}")
        raise server_error(f"Failed to queue invitation email: {str(e)}")

    # Audit log
    ip_address, user_agent = extract_client_metadata(request)
    from app.services.audit_service import AuditService
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="RESEND_INVITATION",
        resource_type="USER",
        resource_id=invitee_id,
        details={
            "invitee_email": invitee.email,
            "sponsor_id": current_user.id,
            "event_id": event.id,
            "event_name": event.name
        },
        ip_address=ip_address,
        user_agent=user_agent
    )

    return {
        "success": True,
        "message": f"Invitation email queued for {invitee.email}",
        "queue_id": queue_entry.id,
        "confirmation_code_updated": True
    }
