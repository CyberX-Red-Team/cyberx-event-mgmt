"""Pydantic schemas for agent task system."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# --- Agent-facing schemas ---

class AgentTaskResponse(BaseModel):
    """Task as seen by the agent."""
    id: int
    task_type: str
    payload: Optional[dict] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class AgentTaskListResponse(BaseModel):
    """List of pending tasks for the agent."""
    tasks: list[AgentTaskResponse]


class AgentTaskUpdateRequest(BaseModel):
    """Agent reporting task progress/completion."""
    status: str  # IN_PROGRESS, COMPLETED, FAILED
    result: Optional[dict] = None
    error_message: Optional[str] = None


class AgentVPNConfigResponse(BaseModel):
    """New VPN config returned after cycle_vpn."""
    config: str
    ipv4_address: str
    interface_ip: str
    endpoint: str


class AgentVPNConfigRequest(BaseModel):
    """Request body for VPN config (requires task_id)."""
    task_id: int


# --- Participant/Admin-facing schemas ---

class CreateTaskRequest(BaseModel):
    """Create a task for an instance."""
    task_type: str  # e.g. "cycle_vpn"
    payload: Optional[dict] = None


class TaskHistoryResponse(BaseModel):
    """Task history entry."""
    id: int
    task_type: str
    payload: Optional[dict] = None
    status: str
    result: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by_user_id: Optional[int] = None

    class Config:
        from_attributes = True


class TaskHistoryListResponse(BaseModel):
    """List of task history entries."""
    tasks: list[TaskHistoryResponse]


class AgentStatusResponse(BaseModel):
    """Agent status for an instance."""
    agent_registered: bool
    agent_last_heartbeat: Optional[datetime] = None
    agent_registered_ip: Optional[str] = None
    pending_tasks: int
