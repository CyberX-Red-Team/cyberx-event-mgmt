"""Admin routes for managing participant actions."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime, timezone

from app.database import get_db
from app.models.user import User
from app.models.participant_action import ParticipantAction, ActionType, ActionStatus
from app.models.event import Event
from app.models.email_queue import EmailQueue, EmailQueueStatus
from app.models.email_template import EmailTemplate
from app.dependencies import get_current_admin_user
from app.services.workflow_service import WorkflowService
from app.models.email_workflow import WorkflowTriggerEvent
from app.services.audit_service import AuditService
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin/actions", tags=["admin-actions"])


# Schemas
class BulkActionCreate(BaseModel):
    """Request to create action for multiple participants."""
    action_type: str  # ActionType value
    title: str
    description: Optional[str] = None
    deadline: Optional[datetime] = None
    user_ids: List[int]  # Empty list means "all confirmed participants"
    send_notification: bool = True
    email_template_id: Optional[int] = None  # Optional custom SendGrid template


class ActionResponse(BaseModel):
    """Response for participant action."""
    id: int
    user_id: int
    user_email: str
    user_name: str
    event_id: int
    action_type: str
    title: str
    description: Optional[str]
    status: str
    responded_at: Optional[datetime]
    response_note: Optional[str]
    deadline: Optional[datetime]
    created_at: datetime


@router.post("/bulk")
async def create_bulk_action(
    data: BulkActionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """
    Create action for selected participants or all confirmed participants.

    If user_ids is empty, applies to all confirmed participants for current event.
    """
    # Get current active event
    event_result = await db.execute(
        select(Event).where(Event.is_active == True)
    )
    event = event_result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=400, detail="No active event found")

    # Determine target users
    if data.user_ids:
        # Specific users selected
        user_result = await db.execute(
            select(User).where(User.id.in_(data.user_ids))
        )
        target_users = user_result.scalars().all()
    else:
        # All confirmed participants for current event
        from app.models.event import EventParticipation, ParticipationStatus
        user_result = await db.execute(
            select(User)
            .join(EventParticipation, EventParticipation.user_id == User.id)
            .where(EventParticipation.event_id == event.id)
            .where(EventParticipation.status == ParticipationStatus.CONFIRMED.value)
            .where(User.is_active == True)
        )
        target_users = user_result.scalars().all()

    if not target_users:
        raise HTTPException(status_code=400, detail="No target users found")

    # Create actions
    created_actions = []
    for user in target_users:
        action = ParticipantAction(
            user_id=user.id,
            event_id=event.id,
            created_by_id=current_user.id,
            action_type=data.action_type,
            title=data.title,
            description=data.description,
            status=ActionStatus.PENDING.value,
            deadline=data.deadline,
            email_template_id=data.email_template_id
        )
        db.add(action)
        created_actions.append(action)

    await db.commit()

    # Send notifications
    if data.send_notification:
        if data.email_template_id:
            # Use custom SendGrid template directly
            template_result = await db.execute(
                select(EmailTemplate).where(EmailTemplate.id == data.email_template_id)
            )
            template = template_result.scalar_one_or_none()

            if template and template.sendgrid_template_id:
                for action in created_actions:
                    user = action.user
                    # Queue email with custom template
                    email_queue = EmailQueue(
                        to_email=user.email,
                        to_name=f"{user.first_name} {user.last_name}",
                        subject=f"Action Required: {action.title}",
                        sendgrid_template_id=template.sendgrid_template_id,
                        template_data={
                            "first_name": user.first_name,
                            "last_name": user.last_name,
                            "action_title": action.title,
                            "action_description": action.description or "",
                            "action_url": f"https://staging.events.cyberxredteam.org/portal#actions",
                            "deadline": str(action.deadline) if action.deadline else "No deadline",
                            "event_name": event.name
                        },
                        status=EmailQueueStatus.PENDING,
                        event_id=event.id
                    )
                    db.add(email_queue)
                    action.notification_sent = True
                    action.notification_sent_at = datetime.now(timezone.utc)
        else:
            # Use workflow system (default)
            workflow_service = WorkflowService(db)
            for action in created_actions:
                await workflow_service.trigger_workflow(
                    trigger_event=WorkflowTriggerEvent.ACTION_ASSIGNED,
                    user_id=action.user_id,
                    custom_vars={
                        "action_title": action.title,
                        "action_description": action.description or "",
                        "action_url": f"https://staging.events.cyberxredteam.org/portal#actions",
                        "deadline": str(action.deadline) if action.deadline else "No deadline"
                    }
                )
                action.notification_sent = True
                action.notification_sent_at = datetime.now(timezone.utc)

        await db.commit()

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="bulk_action_create",
        resource_type="participant_action",
        details={"message": f"Created {len(created_actions)} actions of type {data.action_type}"}
    )

    return {
        "success": True,
        "actions_created": len(created_actions),
        "message": f"Successfully created {len(created_actions)} actions"
    }


@router.get("")
async def list_actions(
    event_id: Optional[int] = None,
    action_type: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """List all participant actions with filters."""
    query = select(ParticipantAction).join(User, User.id == ParticipantAction.user_id)

    if event_id:
        query = query.where(ParticipantAction.event_id == event_id)
    if action_type:
        query = query.where(ParticipantAction.action_type == action_type)
    if status:
        query = query.where(ParticipantAction.status == status)

    result = await db.execute(query)
    actions = result.scalars().all()

    # Build response with user info
    response = []
    for action in actions:
        user = action.user
        response.append(ActionResponse(
            id=action.id,
            user_id=user.id,
            user_email=user.email,
            user_name=f"{user.first_name} {user.last_name}",
            event_id=action.event_id,
            action_type=action.action_type,
            title=action.title,
            description=action.description,
            status=action.status,
            responded_at=action.responded_at,
            response_note=action.response_note,
            deadline=action.deadline,
            created_at=action.created_at
        ))

    return response


@router.get("/statistics")
async def get_action_statistics(
    event_id: Optional[int] = None,
    action_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Get summary statistics for actions grouped by action groups."""
    from sqlalchemy import func, case

    # Base query
    query = select(
        ParticipantAction.action_type,
        ParticipantAction.title,
        ParticipantAction.created_at,
        func.count(ParticipantAction.id).label('total'),
        func.sum(case((ParticipantAction.status == ActionStatus.CONFIRMED.value, 1), else_=0)).label('confirmed'),
        func.sum(case((ParticipantAction.status == ActionStatus.DECLINED.value, 1), else_=0)).label('declined'),
        func.sum(case((ParticipantAction.status == ActionStatus.PENDING.value, 1), else_=0)).label('pending'),
    ).group_by(
        ParticipantAction.action_type,
        ParticipantAction.title,
        ParticipantAction.created_at
    ).order_by(ParticipantAction.created_at.desc())

    if event_id:
        query = query.where(ParticipantAction.event_id == event_id)
    if action_type:
        query = query.where(ParticipantAction.action_type == action_type)

    result = await db.execute(query)
    stats = result.all()

    return [
        {
            "action_type": row.action_type,
            "title": row.title,
            "created_at": row.created_at,
            "total": row.total,
            "confirmed": row.confirmed,
            "declined": row.declined,
            "pending": row.pending
        }
        for row in stats
    ]
