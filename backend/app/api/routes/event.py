"""Event API routes for event and participation management."""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_db,
    get_current_admin_user,
    get_current_sponsor_user,
    get_current_active_user
)
from app.api.exceptions import not_found, forbidden, bad_request, conflict, unauthorized, server_error
from app.api.utils.pagination import calculate_pagination
from app.api.utils.dependencies import get_event_service
from app.models.user import User
from app.services.event_service import EventService
from app.schemas.event import (
    EventCreate,
    EventUpdate,
    EventResponse,
    EventListResponse,
    EventParticipationResponse,
    EventParticipationListResponse,
    BulkInviteRequest,
    BulkInviteResponse,
    ConfirmParticipationRequest,
    ConfirmParticipationResponse,
    ParticipationHistoryResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/events", tags=["Events"])


# ============== Event Management (Admin Only) ==============

@router.get("", response_model=EventListResponse)
async def list_events(
    current_user: User = Depends(get_current_sponsor_user),
    service: EventService = Depends(get_event_service)
):
    """List all events."""
    events = await service.list_events()

    items = []
    for event in events:
        stats = await service.get_event_statistics(event.id)
        items.append(EventResponse(
            id=event.id,
            year=event.year,
            name=event.name,
            start_date=event.start_date,
            end_date=event.end_date,
            event_time=event.event_time,
            event_location=event.event_location,
            terms_version=event.terms_version,
            is_active=event.is_active,
            created_at=event.created_at,
            updated_at=event.updated_at,
            total_invited=stats["total_invited"],
            total_confirmed=stats["total_confirmed"],
            total_declined=stats["total_declined"],
            total_no_response=stats["total_no_response"]
        ))

    return EventListResponse(items=items, total=len(items))


@router.get("/active")
async def get_active_event(
    current_user: User = Depends(get_current_active_user),
    service: EventService = Depends(get_event_service)
):
    """Get the currently active event."""
    event = await service.get_active_event()
    if not event:
        return {"active": False, "event": None}

    return {
        "active": True,
        "event": EventResponse(
            id=event.id,
            year=event.year,
            name=event.name,
            start_date=event.start_date,
            end_date=event.end_date,
            event_time=event.event_time,
            event_location=event.event_location,
            terms_version=event.terms_version,
            is_active=event.is_active,
            vpn_available=getattr(event, 'vpn_available', False),
            test_mode=getattr(event, 'test_mode', False),
            created_at=event.created_at,
            updated_at=event.updated_at
        )
    }


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: int,
    current_user: User = Depends(get_current_sponsor_user),
    service: EventService = Depends(get_event_service)
):
    """Get a specific event by ID."""
    event = await service.get_event(event_id)
    if not event:
        raise not_found("Event not found")

    return EventResponse(
        id=event.id,
        year=event.year,
        name=event.name,
        start_date=event.start_date,
        end_date=event.end_date,
        event_time=event.event_time,
        event_location=event.event_location,
        terms_version=event.terms_version,
        is_active=event.is_active,
        vpn_available=getattr(event, 'vpn_available', False),
        test_mode=getattr(event, 'test_mode', False),
        created_at=event.created_at,
        updated_at=event.updated_at
    )


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    data: EventCreate,
    current_user: User = Depends(get_current_admin_user),
    service: EventService = Depends(get_event_service)
):
    """Create a new event. Admin only."""
    # Check if year already exists
    existing = await service.get_event_by_year(data.year)
    if existing:
        raise bad_request(f"An event for year {data.year} already exists")

    event = await service.create_event(
        year=data.year,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
        terms_version=data.terms_version,
        terms_content=data.terms_content,
        is_active=data.is_active
    )

    return EventResponse(
        id=event.id,
        year=event.year,
        name=event.name,
        start_date=event.start_date,
        end_date=event.end_date,
        event_time=event.event_time,
        event_location=event.event_location,
        terms_version=event.terms_version,
        is_active=event.is_active,
        vpn_available=getattr(event, 'vpn_available', False),
        test_mode=getattr(event, 'test_mode', False),
        created_at=event.created_at,
        updated_at=event.updated_at
    )


@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: int,
    data: EventUpdate,
    current_user: User = Depends(get_current_admin_user),
    service: EventService = Depends(get_event_service)
):
    """Update an event. Admin only."""
    # Get event before update to check old values
    old_event = await service.get_event(event_id)
    if not old_event:
        raise not_found("Event not found")

    old_is_active = old_event.is_active
    old_test_mode = getattr(old_event, 'test_mode', False)
    old_registration_open = getattr(old_event, 'registration_open', False)

    # Update the event
    event = await service.update_event(event_id, **data.model_dump(exclude_unset=True))
    if not event:
        raise not_found("Event not found")

    # Check what changed
    new_is_active = event.is_active
    new_test_mode = getattr(event, 'test_mode', False)
    new_registration_open = getattr(event, 'registration_open', False)

    became_active = not old_is_active and new_is_active
    entered_test_mode = not old_test_mode and new_test_mode
    exited_test_mode = old_test_mode and not new_test_mode
    registration_opened = not old_registration_open and new_registration_open

    logger.info(
        f"Event {event_id} update check: "
        f"became_active={became_active}, entered_test_mode={entered_test_mode}, "
        f"exited_test_mode={exited_test_mode}, registration_opened={registration_opened}, "
        f"is_active={new_is_active}"
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
        (exited_test_mode and event.is_active and new_registration_open)
    )

    if should_trigger:
        logger.info(
            f"Triggering invitation email workflow for event {event.name} (ID: {event.id}) "
            f"[became_active={became_active}, entered_test_mode={entered_test_mode}, "
            f"exited_test_mode={exited_test_mode}, registration_opened={registration_opened}, "
            f"test_mode={new_test_mode}]"
        )
        from app.tasks.invitation_emails import schedule_invitation_emails
        schedule_invitation_emails(event.id, event.name, test_mode=new_test_mode)
        logger.info(
            f"Invitation email workflow scheduled for event {event.name} "
            f"[test_mode={new_test_mode}]"
        )

    return EventResponse(
        id=event.id,
        year=event.year,
        name=event.name,
        start_date=event.start_date,
        end_date=event.end_date,
        event_time=event.event_time,
        event_location=event.event_location,
        terms_version=event.terms_version,
        is_active=event.is_active,
        vpn_available=getattr(event, 'vpn_available', False),
        test_mode=getattr(event, 'test_mode', False),
        created_at=event.created_at,
        updated_at=event.updated_at
    )


@router.delete("/{event_id}")
async def delete_event(
    event_id: int,
    current_user: User = Depends(get_current_admin_user),
    service: EventService = Depends(get_event_service)
):
    """Delete an event. Admin only."""
    success = await service.delete_event(event_id)
    if not success:
        raise not_found("Event not found")

    return {"message": "Event deleted successfully"}


# ============== Participation Management ==============

@router.get("/{event_id}/participants", response_model=EventParticipationListResponse)
async def list_event_participants(
    event_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status: invited, confirmed, declined, no_response"),
    current_user: User = Depends(get_current_sponsor_user),
    service: EventService = Depends(get_event_service)
):
    """List participants for an event."""
    event = await service.get_event(event_id)
    if not event:
        raise not_found("Event not found")

    participations, total = await service.get_event_participants(
        event_id=event_id,
        status=status,
        page=page,
        page_size=page_size
    )

    items = []
    for p in participations:
        items.append(EventParticipationResponse(
            id=p.id,
            user_id=p.user_id,
            event_id=p.event_id,
            status=p.status,
            invited_at=p.invited_at,
            terms_accepted_at=p.terms_accepted_at,
            confirmed_at=p.confirmed_at,
            declined_at=p.declined_at,
            declined_reason=p.declined_reason,
            created_at=p.created_at,
            updated_at=p.updated_at,
            event_year=event.year,
            event_name=event.name
        ))

    _, total_pages = calculate_pagination(total, page, page_size)

    return EventParticipationListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post("/{event_id}/invite", response_model=BulkInviteResponse)
async def bulk_invite_to_event(
    event_id: int,
    data: BulkInviteRequest,
    current_user: User = Depends(get_current_admin_user),
    service: EventService = Depends(get_event_service)
):
    """Bulk invite users to an event. Admin only."""
    if data.event_id != event_id:
        raise bad_request("Event ID in URL does not match request body")

    event = await service.get_event(event_id)
    if not event:
        raise not_found("Event not found")

    invited_count, already_invited_count, failed_ids = await service.bulk_invite_to_event(
        user_ids=data.user_ids,
        event_id=event_id
    )

    return BulkInviteResponse(
        success=True,
        message=f"Invited {invited_count} users, {already_invited_count} already invited",
        invited_count=invited_count,
        already_invited_count=already_invited_count,
        failed_ids=failed_ids
    )


# ============== Participant Self-Service ==============

@router.get("/my/history", response_model=ParticipationHistoryResponse)
async def get_my_participation_history(
    current_user: User = Depends(get_current_active_user),
    service: EventService = Depends(get_event_service)
):
    """Get current user's participation history."""
    history = await service.get_user_participation_history(current_user.id)

    items = []
    for p in history:
        items.append(EventParticipationResponse(
            id=p.id,
            user_id=p.user_id,
            event_id=p.event_id,
            status=p.status,
            invited_at=p.invited_at,
            terms_accepted_at=p.terms_accepted_at,
            confirmed_at=p.confirmed_at,
            declined_at=p.declined_at,
            declined_reason=p.declined_reason,
            created_at=p.created_at,
            updated_at=p.updated_at,
            event_year=p.event.year if p.event else None,
            event_name=p.event.name if p.event else None
        ))

    return ParticipationHistoryResponse(
        user_id=current_user.id,
        total_years_invited=current_user.years_invited,
        total_years_participated=current_user.years_participated,
        participation_rate=current_user.participation_rate,
        is_chronic_non_participant=current_user.is_chronic_non_participant,
        should_recommend_removal=current_user.should_recommend_removal,
        history=items
    )


@router.post("/my/confirm", response_model=ConfirmParticipationResponse)
async def confirm_my_participation(
    data: ConfirmParticipationRequest,
    current_user: User = Depends(get_current_active_user),
    service: EventService = Depends(get_event_service)
):
    """Confirm participation for an event."""
    success, message, participation = await service.confirm_participation(
        user_id=current_user.id,
        event_id=data.event_id,
        accept_terms=data.accept_terms
    )

    if not success:
        raise bad_request(message)

    return ConfirmParticipationResponse(
        success=True,
        message=message,
        participation=EventParticipationResponse(
            id=participation.id,
            user_id=participation.user_id,
            event_id=participation.event_id,
            status=participation.status,
            invited_at=participation.invited_at,
            terms_accepted_at=participation.terms_accepted_at,
            confirmed_at=participation.confirmed_at,
            declined_at=participation.declined_at,
            declined_reason=participation.declined_reason,
            created_at=participation.created_at,
            updated_at=participation.updated_at
        ) if participation else None
    )


@router.post("/my/decline")
async def decline_my_participation(
    event_id: int,
    reason: Optional[str] = Query(None, description="Reason for declining"),
    current_user: User = Depends(get_current_active_user),
    service: EventService = Depends(get_event_service)
):
    """Decline participation for an event."""
    success, message, participation = await service.decline_participation(
        user_id=current_user.id,
        event_id=event_id,
        reason=reason
    )

    if not success:
        raise bad_request(message)

    return {"success": True, "message": message}


# ============== Admin Reports ==============

@router.get("/reports/chronic-non-participants")
async def get_chronic_non_participants(
    current_user: User = Depends(get_current_admin_user),
    service: EventService = Depends(get_event_service)
):
    """Get list of chronic non-participants (invited 3+ years, never participated)."""
    users = await service.get_chronic_non_participants()

    return {
        "total": len(users),
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "years_invited": u.years_invited,
                "years_participated": u.years_participated
            }
            for u in users
        ]
    }


@router.get("/reports/recommended-removals")
async def get_recommended_removals(
    current_user: User = Depends(get_current_admin_user),
    service: EventService = Depends(get_event_service)
):
    """Get list of invitees recommended for removal based on participation history."""
    users = await service.get_recommended_removals()

    return {
        "total": len(users),
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "years_invited": u.years_invited,
                "years_participated": u.years_participated,
                "participation_rate": u.participation_rate,
                "is_chronic_non_participant": u.is_chronic_non_participant
            }
            for u in users
        ]
    }
