"""Participant routes for viewing and responding to actions."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from datetime import datetime, timezone

from app.database import get_db
from app.models.user import User
from app.models.participant_action import ParticipantAction, ActionStatus
from app.dependencies import get_current_user
from app.services.audit_service import AuditService
from pydantic import BaseModel

router = APIRouter(prefix="/api/participants/actions", tags=["participant-actions"])


class ActionRespondRequest(BaseModel):
    """Request to respond to an action."""
    status: str  # "confirmed" or "declined"
    response_note: Optional[str] = None


class ActionListResponse(BaseModel):
    """Response for participant action list."""
    id: int
    action_type: str
    title: str
    description: Optional[str]
    status: str
    responded_at: Optional[datetime]
    response_note: Optional[str]
    deadline: Optional[datetime]
    created_at: datetime


@router.get("/my-actions")
async def get_my_actions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all actions assigned to current user."""
    result = await db.execute(
        select(ParticipantAction)
        .where(ParticipantAction.user_id == current_user.id)
        .order_by(ParticipantAction.created_at.desc())
    )
    actions = result.scalars().all()

    return [
        ActionListResponse(
            id=action.id,
            action_type=action.action_type,
            title=action.title,
            description=action.description,
            status=action.status,
            responded_at=action.responded_at,
            response_note=action.response_note,
            deadline=action.deadline,
            created_at=action.created_at
        )
        for action in actions
    ]


@router.get("/pending-count")
async def get_pending_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get count of pending actions for badge display."""
    result = await db.execute(
        select(func.count(ParticipantAction.id))
        .where(ParticipantAction.user_id == current_user.id)
        .where(ParticipantAction.status == ActionStatus.PENDING.value)
    )
    count = result.scalar()
    return {"pending_count": count}


@router.post("/{action_id}/respond")
async def respond_to_action(
    action_id: int,
    data: ActionRespondRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Respond to an assigned action (confirm or decline)."""
    # Get action
    result = await db.execute(
        select(ParticipantAction).where(ParticipantAction.id == action_id)
    )
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    # Verify ownership
    if action.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Verify not already responded
    if action.status != ActionStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Action already responded to")

    # Validate status
    if data.status not in [ActionStatus.CONFIRMED.value, ActionStatus.DECLINED.value]:
        raise HTTPException(status_code=400, detail="Invalid status")

    # Update action
    action.status = data.status
    action.responded_at = datetime.now(timezone.utc)
    action.response_note = data.response_note

    # Update related fields based on action type
    if action.action_type == "in_person_attendance":
        if data.status == ActionStatus.CONFIRMED.value:
            current_user.confirmed_in_person = True
        elif data.status == ActionStatus.DECLINED.value:
            current_user.confirmed_in_person = False

    await db.commit()

    # Audit log
    audit_service = AuditService(db)
    await audit_service.log_action(
        user_id=current_user.id,
        action="action_respond",
        resource_type="participant_action",
        resource_id=action_id,
        details=f"Responded {data.status} to action: {action.title}"
    )

    return {
        "success": True,
        "message": f"Action {data.status}"
    }
