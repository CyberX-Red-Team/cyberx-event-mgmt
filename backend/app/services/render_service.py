"""Render.com API service for managing Gotenberg lifecycle (suspend/resume/scale)."""
import asyncio
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

RENDER_API_BASE = "https://api.render.com/v1"


class RenderServiceManager:
    """Manages the Gotenberg private service on Render via their API."""

    def __init__(self):
        settings = get_settings()
        self.api_key: Optional[str] = getattr(settings, "RENDER_API_KEY", None)
        self.service_id: Optional[str] = getattr(settings, "GOTENBERG_RENDER_SERVICE_ID", None)
        self.gotenberg_url: Optional[str] = getattr(settings, "GOTENBERG_URL", None)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.service_id)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def scale_gotenberg(self, plan: str = "standard") -> bool:
        """Scale the Gotenberg service to a different plan (e.g. 'starter', 'standard')."""
        if not self.enabled:
            logger.info("Render API not configured, skipping scale")
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{RENDER_API_BASE}/services/{self.service_id}",
                headers=self._headers(),
                json={"plan": plan},
                timeout=30.0,
            )
            if resp.status_code == 200:
                logger.info(f"Scaled Gotenberg to plan: {plan}")
                return True
            else:
                logger.error(f"Failed to scale Gotenberg: {resp.status_code} {resp.text}")
                return False

    async def resume_gotenberg(self) -> bool:
        """Resume the Gotenberg service if suspended."""
        if not self.enabled:
            logger.info("Render API not configured, skipping resume")
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_API_BASE}/services/{self.service_id}/resume",
                headers=self._headers(),
                timeout=30.0,
            )
            if resp.status_code in (200, 202):
                logger.info("Gotenberg resume requested")
                return True
            else:
                logger.error(f"Failed to resume Gotenberg: {resp.status_code} {resp.text}")
                return False

    async def suspend_gotenberg(self) -> bool:
        """Suspend the Gotenberg service."""
        if not self.enabled:
            logger.info("Render API not configured, skipping suspend")
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_API_BASE}/services/{self.service_id}/suspend",
                headers=self._headers(),
                timeout=30.0,
            )
            if resp.status_code in (200, 202):
                logger.info("Gotenberg suspend requested")
                return True
            else:
                logger.error(f"Failed to suspend Gotenberg: {resp.status_code} {resp.text}")
                return False

    async def wait_for_gotenberg_ready(self, timeout: int = 120, interval: int = 5) -> bool:
        """Poll Gotenberg's health endpoint until it responds, with timeout."""
        if not self.gotenberg_url:
            logger.warning("GOTENBERG_URL not set, cannot wait for readiness")
            return False

        health_url = f"{self.gotenberg_url}/health"
        elapsed = 0
        logger.info(f"Waiting for Gotenberg to be ready at {health_url} (timeout={timeout}s)")

        async with httpx.AsyncClient() as client:
            while elapsed < timeout:
                try:
                    resp = await client.get(health_url, timeout=5.0)
                    if resp.status_code == 200:
                        logger.info(f"Gotenberg ready after {elapsed}s")
                        return True
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass

                await asyncio.sleep(interval)
                elapsed += interval

        logger.error(f"Gotenberg not ready after {timeout}s")
        return False

    async def start_gotenberg(self, plan: str = "standard") -> bool:
        """Scale, resume, and wait for Gotenberg to be ready. Returns True if ready."""
        if not self.enabled:
            logger.info("Render API not configured, skipping Gotenberg start")
            return True  # Assume it's already running (local dev)

        logger.info("Starting Gotenberg lifecycle: scale → resume → wait")
        await self.scale_gotenberg(plan)
        await self.resume_gotenberg()
        return await self.wait_for_gotenberg_ready()

    async def stop_gotenberg(self) -> bool:
        """Suspend Gotenberg after use."""
        if not self.enabled:
            return True
        logger.info("Stopping Gotenberg: suspend")
        return await self.suspend_gotenberg()
