"""Admin routes for managing participant actions."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime, timezone
import uuid

from app.database import get_db
from app.models.user import User
from app.models.participant_action import ParticipantAction, ActionType, ActionStatus
from app.models.event import Event
from app.models.email_template import EmailTemplate
from app.dependencies import get_current_admin_user
from app.services.workflow_service import WorkflowService
from app.services.email_queue_service import EmailQueueService
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
    batch_id: Optional[str]
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
    batch_id = f"action_{uuid.uuid4().hex[:12]}"
    created_actions = []
    for user in target_users:
        action = ParticipantAction(
            user_id=user.id,
            event_id=event.id,
            created_by_id=current_user.id,
            batch_id=batch_id,
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
        notification_vars = {
            "action_title": data.title,
            "action_description": data.description or "",
            "action_url": f"https://staging.events.cyberxredteam.org/portal#actions",
            "deadline": str(data.deadline) if data.deadline else "No deadline",
            "event_name": event.name
        }

        if data.email_template_id:
            # Use custom SendGrid template via queue
            template_result = await db.execute(
                select(EmailTemplate).where(EmailTemplate.id == data.email_template_id)
            )
            template = template_result.scalar_one_or_none()

            if template:
                queue_service = EmailQueueService(db)
                for action in created_actions:
                    await queue_service.enqueue_email(
                        user_id=action.user_id,
                        template_name=template.name,
                        priority=3,
                        custom_vars=notification_vars,
                        force=True,
                    )
                    action.notification_sent = True
                    action.notification_sent_at = datetime.now(timezone.utc)
        else:
            # Use workflow system (default)
            # Try action-type-specific trigger first, fall back to generic ACTION_ASSIGNED
            action_type_trigger_map = {
                ActionType.IN_PERSON_ATTENDANCE.value: WorkflowTriggerEvent.ACTION_ASSIGNED_IN_PERSON_ATTENDANCE,
                ActionType.SURVEY_COMPLETION.value: WorkflowTriggerEvent.ACTION_ASSIGNED_SURVEY_COMPLETION,
                ActionType.ORIENTATION_RSVP.value: WorkflowTriggerEvent.ACTION_ASSIGNED_ORIENTATION_RSVP,
                ActionType.DOCUMENT_REVIEW.value: WorkflowTriggerEvent.ACTION_ASSIGNED_DOCUMENT_REVIEW,
            }
            trigger_event = action_type_trigger_map.get(data.action_type, WorkflowTriggerEvent.ACTION_ASSIGNED)

            workflow_service = WorkflowService(db)
            for action in created_actions:
                await workflow_service.trigger_workflow(
                    trigger_event=trigger_event,
                    user_id=action.user_id,
                    custom_vars=notification_vars,
                    force=True,
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


class BulkActionRevoke(BaseModel):
    """Request to revoke actions by batch_id."""
    batch_id: str


@router.post("/revoke")
async def revoke_actions(
    data: BulkActionRevoke,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """
    Revoke all pending actions in a batch.

    Sets PENDING actions to CANCELLED. Already confirmed/declined actions are not changed.
    """
    from sqlalchemy import and_

    # Find all pending actions in this batch
    result = await db.execute(
        select(ParticipantAction).where(
            and_(
                ParticipantAction.batch_id == data.batch_id,
                ParticipantAction.status == ActionStatus.PENDING.value
            )
        )
    )
    pending_actions = result.scalars().all()

    if not pending_actions:
        return {
            "success": True,
            "actions_revoked": 0,
            "message": "No pending actions to revoke"
        }

    # Cancel the actions
    now = datetime.now(timezone.utc)
    for action in pending_actions:
        action.status = ActionStatus.CANCELLED.value
        action.responded_at = now
        action.response_note = f"Revoked by admin {current_user.email}"

    await db.commit()

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log(
        user_id=current_user.id,
        action="bulk_action_revoke",
        resource_type="participant_action",
        details={
            "message": f"Revoked {len(pending_actions)} pending actions",
            "batch_id": data.batch_id
        }
    )

    return {
        "success": True,
        "actions_revoked": len(pending_actions),
        "message": f"Revoked {len(pending_actions)} pending actions"
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
    from sqlalchemy.orm import selectinload

    query = select(ParticipantAction).options(selectinload(ParticipantAction.user))

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
            batch_id=action.batch_id,
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
    """Get summary statistics for actions grouped by batch."""
    from sqlalchemy import func, case

    # Group by batch_id for clean separation of batches.
    # Falls back to action_type+title grouping for legacy actions without batch_id.
    query = select(
        ParticipantAction.batch_id,
        ParticipantAction.action_type,
        ParticipantAction.title,
        func.min(ParticipantAction.created_at).label('created_at'),
        func.count(ParticipantAction.id).label('total'),
        func.sum(case((ParticipantAction.status == ActionStatus.CONFIRMED.value, 1), else_=0)).label('confirmed'),
        func.sum(case((ParticipantAction.status == ActionStatus.DECLINED.value, 1), else_=0)).label('declined'),
        func.sum(case((ParticipantAction.status == ActionStatus.PENDING.value, 1), else_=0)).label('pending'),
        func.sum(case((ParticipantAction.status == ActionStatus.CANCELLED.value, 1), else_=0)).label('cancelled'),
    ).group_by(
        ParticipantAction.batch_id,
        ParticipantAction.action_type,
        ParticipantAction.title
    ).order_by(func.min(ParticipantAction.created_at).desc())

    if event_id:
        query = query.where(ParticipantAction.event_id == event_id)
    if action_type:
        query = query.where(ParticipantAction.action_type == action_type)

    result = await db.execute(query)
    stats = result.all()

    return [
        {
            "batch_id": row.batch_id,
            "action_type": row.action_type,
            "title": row.title,
            "created_at": row.created_at,
            "total": row.total,
            "confirmed": row.confirmed,
            "declined": row.declined,
            "pending": row.pending,
            "cancelled": row.cancelled
        }
        for row in stats
    ]
