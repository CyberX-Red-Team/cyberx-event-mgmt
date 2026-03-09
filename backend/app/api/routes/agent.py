"""Agent API routes — agent-facing, participant-facing, and admin-facing."""
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_db,
    get_current_agent_instance,
    get_current_active_user,
    require_permission,
)
from app.api.exceptions import (
    not_found, bad_request, forbidden, rate_limited,
)
from app.models.instance import Instance
from app.models.agent_task import AgentTask
from app.models.user import User
from app.services.agent_service import AgentService
from app.schemas.agent import (
    AgentTaskListResponse,
    AgentTaskResponse,
    AgentTaskUpdateRequest,
    AgentVPNConfigRequest,
    AgentVPNConfigResponse,
    CreateTaskRequest,
    TaskHistoryListResponse,
    TaskHistoryResponse,
    AgentStatusResponse,
)

logger = logging.getLogger(__name__)

# ─── Agent-facing routes (Bearer token auth) ───────────────────────

agent_router = APIRouter(
    prefix="/api/agent", tags=["Instance Agent"]
)

# Directory containing agent install files (repo root / agent /)
_AGENT_DIR = Path(__file__).resolve().parents[4] / "agent"


@agent_router.get("/install/cyberx-agent.py", response_class=PlainTextResponse)
async def download_agent_script():
    """Serve the agent script (unauthenticated — no secrets in file)."""
    path = _AGENT_DIR / "cyberx-agent.py"
    if not path.exists():
        raise not_found("Agent script")
    return PlainTextResponse(path.read_text(), media_type="text/x-python")


@agent_router.get(
    "/install/cyberx-agent.service", response_class=PlainTextResponse
)
async def download_agent_service_unit():
    """Serve the systemd unit file (unauthenticated)."""
    path = _AGENT_DIR / "cyberx-agent.service"
    if not path.exists():
        raise not_found("Agent service unit")
    return PlainTextResponse(path.read_text(), media_type="text/plain")


@agent_router.get("/tasks", response_model=AgentTaskListResponse)
async def poll_tasks(
    instance: Instance = Depends(get_current_agent_instance),
    db: AsyncSession = Depends(get_db),
):
    """Poll for pending tasks. Also updates heartbeat."""
    service = AgentService(db)
    await service.update_heartbeat(instance)
    tasks = await service.get_pending_tasks(instance.id)
    return AgentTaskListResponse(
        tasks=[AgentTaskResponse.model_validate(t) for t in tasks]
    )


@agent_router.patch(
    "/tasks/{task_id}", response_model=AgentTaskResponse
)
async def update_task(
    task_id: int,
    body: AgentTaskUpdateRequest,
    instance: Instance = Depends(get_current_agent_instance),
    db: AsyncSession = Depends(get_db),
):
    """Update task status (IN_PROGRESS, COMPLETED, FAILED)."""
    if body.status not in ("IN_PROGRESS", "COMPLETED", "FAILED"):
        raise bad_request(
            "status must be IN_PROGRESS, COMPLETED, or FAILED"
        )

    service = AgentService(db)
    task = await service.get_task(task_id, instance.id)
    if not task:
        raise not_found("Task", task_id)

    task = await service.update_task_status(
        task,
        status=body.status,
        result=body.result,
        error_message=body.error_message,
    )
    return AgentTaskResponse.model_validate(task)


@agent_router.post("/heartbeat")
async def heartbeat(
    instance: Instance = Depends(get_current_agent_instance),
    db: AsyncSession = Depends(get_db),
):
    """Explicit heartbeat (task polling also updates it)."""
    service = AgentService(db)
    await service.update_heartbeat(instance)
    return {"status": "ok"}


@agent_router.post(
    "/vpn/new-config", response_model=AgentVPNConfigResponse
)
async def get_new_vpn_config(
    body: AgentVPNConfigRequest,
    instance: Instance = Depends(get_current_agent_instance),
    db: AsyncSession = Depends(get_db),
):
    """Request a new VPN config (requires active cycle_vpn task)."""
    service = AgentService(db)

    # Validate task
    task = await service.get_task(body.task_id, instance.id)
    if not task:
        raise not_found("Task", body.task_id)
    if task.task_type != "cycle_vpn":
        raise bad_request("Task is not a cycle_vpn task")
    if task.status != "IN_PROGRESS":
        raise bad_request(
            "Task must be IN_PROGRESS to request VPN config"
        )

    try:
        result = await service.cycle_vpn(instance, task)
    except ValueError as e:
        raise bad_request(str(e))

    return AgentVPNConfigResponse(**result)


# ─── Participant-facing routes (session auth, scoped) ──────────────

participant_router = APIRouter(
    prefix="/api/instances", tags=["Participant Portal"]
)

ALLOWED_TASK_TYPES = {"cycle_vpn"}


async def _get_owned_instance(
    instance_id: int,
    user: User,
    db: AsyncSession,
) -> Instance:
    """Fetch instance and verify ownership."""
    result = await db.execute(
        select(Instance).where(
            Instance.id == instance_id,
            Instance.deleted_at.is_(None),
        )
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise not_found("Instance", instance_id)
    if instance.assigned_to_user_id != user.id:
        raise forbidden("Not your instance")
    return instance


@participant_router.post(
    "/{instance_id}/tasks", response_model=TaskHistoryResponse
)
async def create_instance_task(
    instance_id: int,
    body: CreateTaskRequest,
    user: User = Depends(require_permission("instances.manage_agent")),
    db: AsyncSession = Depends(get_db),
):
    """Create a task for an owned instance (e.g. cycle_vpn)."""
    if body.task_type not in ALLOWED_TASK_TYPES:
        raise bad_request(
            f"Unsupported task type: {body.task_type}. "
            f"Allowed: {', '.join(ALLOWED_TASK_TYPES)}"
        )

    instance = await _get_owned_instance(instance_id, user, db)

    # Check agent is registered
    if not instance.agent_token_hash:
        raise bad_request("Instance does not have an agent configured")

    service = AgentService(db)

    # Rate limit: 1 per 5 minutes per task type
    if await service.check_rate_limit(instance.id, body.task_type):
        raise rate_limited(
            "Please wait at least 5 minutes between tasks of this type"
        )

    task = await service.create_task(
        instance_id=instance.id,
        task_type=body.task_type,
        created_by_user_id=user.id,
        payload=body.payload,
    )
    return TaskHistoryResponse.model_validate(task)


@participant_router.get(
    "/{instance_id}/tasks",
    response_model=TaskHistoryListResponse,
)
async def get_instance_tasks(
    instance_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """View task history for an owned instance."""
    instance = await _get_owned_instance(instance_id, user, db)
    service = AgentService(db)
    tasks = await service.get_task_history(instance.id)
    return TaskHistoryListResponse(
        tasks=[TaskHistoryResponse.model_validate(t) for t in tasks]
    )


@participant_router.get(
    "/{instance_id}/agent-status",
    response_model=AgentStatusResponse,
)
async def get_agent_status(
    instance_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Check agent status for an owned instance."""
    instance = await _get_owned_instance(instance_id, user, db)

    # Count pending tasks
    result = await db.execute(
        select(func.count(AgentTask.id)).where(
            AgentTask.instance_id == instance.id,
            AgentTask.status == "PENDING",
        )
    )
    pending = result.scalar() or 0

    return AgentStatusResponse(
        agent_registered=instance.agent_token_hash is not None,
        agent_last_heartbeat=instance.agent_last_heartbeat,
        agent_registered_ip=instance.agent_registered_ip,
        pending_tasks=pending,
    )


# ─── Admin-facing routes (session auth, any instance) ──────────────

admin_router = APIRouter(
    prefix="/api/admin/instances", tags=["Admin - Instances"]
)


@admin_router.post(
    "/{instance_id}/tasks", response_model=TaskHistoryResponse
)
async def admin_create_task(
    instance_id: int,
    body: CreateTaskRequest,
    user: User = Depends(require_permission("instances.manage_agent")),
    db: AsyncSession = Depends(get_db),
):
    """Create a task for any instance (admin)."""
    result = await db.execute(
        select(Instance).where(
            Instance.id == instance_id,
            Instance.deleted_at.is_(None),
        )
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise not_found("Instance", instance_id)

    if not instance.agent_token_hash:
        raise bad_request("Instance does not have an agent configured")

    service = AgentService(db)
    task = await service.create_task(
        instance_id=instance.id,
        task_type=body.task_type,
        created_by_user_id=user.id,
        payload=body.payload,
    )
    return TaskHistoryResponse.model_validate(task)


@admin_router.get(
    "/{instance_id}/tasks",
    response_model=TaskHistoryListResponse,
)
async def admin_get_instance_tasks(
    instance_id: int,
    user: User = Depends(require_permission("instances.manage_agent")),
    db: AsyncSession = Depends(get_db),
):
    """List task history for any instance (admin)."""
    service = AgentService(db)
    tasks = await service.get_task_history(instance_id)
    return TaskHistoryListResponse(
        tasks=[TaskHistoryResponse.model_validate(t) for t in tasks]
    )
