"""Agent task management service."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.agent_task import AgentTask
from app.models.instance import Instance
from app.models.vpn import VPNCredential
from app.services.vpn_service import VPNService

logger = logging.getLogger(__name__)


class AgentService:
    """Manages agent tasks and VPN cycling."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    async def get_pending_tasks(self, instance_id: int) -> list[AgentTask]:
        """Get pending tasks for an instance."""
        result = await self.session.execute(
            select(AgentTask)
            .where(
                AgentTask.instance_id == instance_id,
                AgentTask.status == "PENDING",
            )
            .order_by(AgentTask.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_task(
        self, task_id: int, instance_id: int
    ) -> Optional[AgentTask]:
        """Get a task belonging to an instance."""
        result = await self.session.execute(
            select(AgentTask).where(
                AgentTask.id == task_id,
                AgentTask.instance_id == instance_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_task(
        self,
        instance_id: int,
        task_type: str,
        created_by_user_id: int,
        payload: dict | None = None,
    ) -> AgentTask:
        """Create a new task for an instance."""
        task = AgentTask(
            instance_id=instance_id,
            task_type=task_type,
            payload=payload,
            status="PENDING",
            created_by_user_id=created_by_user_id,
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        logger.info(
            "Created %s task %d for instance %d (by user %d)",
            task_type, task.id, instance_id, created_by_user_id,
        )
        return task

    async def update_task_status(
        self,
        task: AgentTask,
        status: str,
        result: dict | None = None,
        error_message: str | None = None,
    ) -> AgentTask:
        """Update task status."""
        now = datetime.now(timezone.utc)
        task.status = status

        if status == "IN_PROGRESS" and task.started_at is None:
            task.started_at = now
        elif status in ("COMPLETED", "FAILED"):
            task.completed_at = now

        if result is not None:
            task.result = result
        if error_message is not None:
            task.error_message = error_message

        await self.session.commit()
        await self.session.refresh(task)
        logger.info(
            "Task %d status → %s (instance %d)",
            task.id, status, task.instance_id,
        )
        return task

    async def update_heartbeat(self, instance: Instance) -> None:
        """Update agent heartbeat timestamp."""
        instance.agent_last_heartbeat = datetime.now(timezone.utc)
        await self.session.commit()

    async def check_rate_limit(
        self, instance_id: int, task_type: str, minutes: int = 5
    ) -> bool:
        """Check if a task of this type was created recently.

        Returns True if rate-limited (too recent), False if OK.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        result = await self.session.execute(
            select(AgentTask).where(
                AgentTask.instance_id == instance_id,
                AgentTask.task_type == task_type,
                AgentTask.created_at > cutoff,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def cycle_vpn(
        self, instance: Instance, task: AgentTask
    ) -> dict:
        """Cycle VPN for an instance: release old, assign new.

        Returns dict with new config and IP info.
        """
        vpn_svc = VPNService(self.session)

        # Find current VPN
        old_vpn = await vpn_svc.get_instance_vpn(instance.id)
        old_vpn_id = old_vpn.id if old_vpn else None

        # Burn old VPN — keep assigned for audit trail, mark unavailable
        if old_vpn:
            old_vpn.is_available = False
            logger.info(
                "Burned VPN %d for instance %d (removed from pool)",
                old_vpn.id, instance.id,
            )

        # Assign new VPN
        success, message, new_vpn = await vpn_svc.assign_vpn_to_instance(
            instance_id=instance.id
        )
        if not success or not new_vpn:
            raise ValueError(f"Failed to assign new VPN: {message}")

        # Update instance VPN IP
        instance.vpn_ip = new_vpn.ipv4_address
        await self.session.commit()

        # Generate WireGuard config
        config = await vpn_svc.generate_wireguard_config(new_vpn)

        logger.info(
            "Cycled VPN for instance %d: old=%s new=%d (ip=%s)",
            instance.id, old_vpn_id, new_vpn.id, new_vpn.ipv4_address,
        )

        return {
            "config": config,
            "ipv4_address": new_vpn.ipv4_address or "",
            "interface_ip": new_vpn.interface_ip,
            "endpoint": new_vpn.endpoint,
        }

    async def get_task_history(
        self, instance_id: int, limit: int = 20
    ) -> list[AgentTask]:
        """Get task history for an instance."""
        result = await self.session.execute(
            select(AgentTask)
            .where(AgentTask.instance_id == instance_id)
            .order_by(AgentTask.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def timeout_stale_tasks(self) -> int:
        """Mark stale IN_PROGRESS tasks as FAILED.

        Returns count of timed-out tasks.
        """
        timeout_minutes = self.settings.AGENT_TASK_TIMEOUT_MINUTES
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=timeout_minutes
        )

        result = await self.session.execute(
            select(AgentTask).where(
                AgentTask.status == "IN_PROGRESS",
                AgentTask.started_at < cutoff,
            )
        )
        stale_tasks = list(result.scalars().all())

        for task in stale_tasks:
            task.status = "FAILED"
            task.completed_at = datetime.now(timezone.utc)
            task.error_message = (
                f"Timed out after {timeout_minutes} minutes"
            )
            logger.warning(
                "Task %d timed out (instance %d, type %s)",
                task.id, task.instance_id, task.task_type,
            )

        if stale_tasks:
            await self.session.commit()

        return len(stale_tasks)
