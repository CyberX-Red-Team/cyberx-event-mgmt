"""Render.com API service for managing sidecar services (suspend/resume/scale/create).

Supports both Gotenberg (legacy convenience methods) and generic sidecar services
like step-ca instances that are created dynamically via the Render API.
"""
import asyncio
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

RENDER_API_BASE = "https://api.render.com/v1"


class RenderServiceManager:
    """Manages sidecar services on Render via their API."""

    def __init__(self):
        settings = get_settings()
        self.api_key: Optional[str] = getattr(settings, "RENDER_API_KEY", None)
        self.service_id: Optional[str] = getattr(settings, "GOTENBERG_RENDER_SERVICE_ID", None)
        self.gotenberg_url: Optional[str] = getattr(settings, "GOTENBERG_URL", None)
        self.render_owner_id: Optional[str] = getattr(settings, "RENDER_OWNER_ID", None)
        self.render_repo_url: Optional[str] = getattr(settings, "RENDER_REPO_URL", None)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

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

    async def _wait_for_deploy_live(self, timeout: int = 180, interval: int = 5) -> bool:
        """Poll the Render deploys API until the latest deploy is 'live'.

        After a resume, Render creates a deploy with trigger 'service_resumed'.
        We wait for that deploy's status to become 'live' before hitting the
        health endpoint, which is much more reliable than blind health polling.
        """
        elapsed = 0
        logger.info(f"Waiting for Render deploy to go live (timeout={timeout}s)")

        async with httpx.AsyncClient() as client:
            while elapsed < timeout:
                try:
                    resp = await client.get(
                        f"{RENDER_API_BASE}/services/{self.service_id}/deploys",
                        headers=self._headers(),
                        params={"limit": 1},
                        timeout=10.0,
                    )
                    if resp.status_code == 200:
                        deploys = resp.json()
                        if deploys and len(deploys) > 0:
                            # Render wraps each deploy in a {"deploy": {...}} envelope
                            deploy_data = deploys[0]
                            deploy = deploy_data.get("deploy", deploy_data)
                            status = deploy.get("status")
                            logger.debug(f"Deploy status: {status} (elapsed={elapsed}s)")
                            if status == "live":
                                logger.info(f"Render deploy is live after {elapsed}s")
                                return True
                            if status in ("build_failed", "update_failed", "canceled"):
                                logger.error(f"Deploy failed with status: {status}")
                                return False
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    logger.debug(f"Deploy check failed: {e}")

                await asyncio.sleep(interval)
                elapsed += interval

        logger.error(f"Deploy not live after {timeout}s")
        return False

    async def wait_for_gotenberg_ready(self, timeout: int = 60, interval: int = 3) -> bool:
        """Poll Gotenberg's health endpoint until it responds.

        This should be called AFTER _wait_for_deploy_live confirms the deploy
        is live, so the timeout can be shorter — it's just waiting for the
        container to finish initializing.
        """
        if not self.gotenberg_url:
            logger.warning("GOTENBERG_URL not set, cannot wait for readiness")
            return False

        health_url = f"{self.gotenberg_url}/health"
        elapsed = 0
        logger.info(f"Waiting for Gotenberg health check at {health_url} (timeout={timeout}s)")

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
        """Scale, resume, and wait for Gotenberg to be ready. Returns True if ready.

        Phase 1: Poll the Render deploys API until deploy status is 'live' (up to 180s).
        Phase 2: Poll Gotenberg's /health endpoint from our service to confirm
                 inter-service routing is established (up to 90s). Render's 'live'
                 status means the container passed its own health checks, but
                 private service routing between Render services can lag behind.
        """
        if not self.enabled:
            logger.info("Render API not configured, skipping Gotenberg start")
            return True  # Assume it's already running (local dev)

        logger.info("Starting Gotenberg lifecycle: scale → resume → deploy live → routing check")
        await self.scale_gotenberg(plan)
        await self.resume_gotenberg()

        deploy_live = await self._wait_for_deploy_live(timeout=180, interval=5)
        if not deploy_live:
            return False

        return await self.wait_for_gotenberg_ready(timeout=90, interval=3)

    async def stop_gotenberg(self) -> bool:
        """Suspend Gotenberg after use."""
        if not self.enabled:
            return True
        logger.info("Stopping Gotenberg: suspend")
        return await self.suspend_gotenberg()

    # -------------------------------------------------------------------------
    # Generic sidecar service methods (for step-ca and other dynamic services)
    # -------------------------------------------------------------------------

    async def resume_service(self, service_id: str) -> bool:
        """Resume a suspended service by its Render service ID."""
        if not self.api_key:
            logger.info("Render API key not configured, skipping resume")
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_API_BASE}/services/{service_id}/resume",
                headers=self._headers(),
                timeout=30.0,
            )
            if resp.status_code in (200, 202):
                logger.info(f"Service {service_id} resume requested")
                return True
            else:
                logger.error(f"Failed to resume service {service_id}: {resp.status_code} {resp.text}")
                return False

    async def suspend_service(self, service_id: str) -> bool:
        """Suspend a running service by its Render service ID."""
        if not self.api_key:
            logger.info("Render API key not configured, skipping suspend")
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_API_BASE}/services/{service_id}/suspend",
                headers=self._headers(),
                timeout=30.0,
            )
            if resp.status_code in (200, 202):
                logger.info(f"Service {service_id} suspend requested")
                return True
            else:
                logger.error(f"Failed to suspend service {service_id}: {resp.status_code} {resp.text}")
                return False

    async def scale_service(self, service_id: str, plan: str) -> bool:
        """Scale a service to a different plan."""
        if not self.api_key:
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{RENDER_API_BASE}/services/{service_id}",
                headers=self._headers(),
                json={"plan": plan},
                timeout=30.0,
            )
            if resp.status_code == 200:
                logger.info(f"Scaled service {service_id} to plan: {plan}")
                return True
            else:
                logger.error(f"Failed to scale service {service_id}: {resp.status_code} {resp.text}")
                return False

    async def get_service_info(self, service_id: str) -> Optional[dict]:
        """Get service details from Render API."""
        if not self.api_key:
            return None

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RENDER_API_BASE}/services/{service_id}",
                headers=self._headers(),
                timeout=15.0,
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error(f"Failed to get service {service_id}: {resp.status_code}")
                return None

    async def wait_for_deploy_live(self, service_id: str, timeout: int = 180, interval: int = 5) -> bool:
        """Poll the Render deploys API until the latest deploy is 'live'."""
        elapsed = 0
        logger.info(f"Waiting for service {service_id} deploy to go live (timeout={timeout}s)")

        async with httpx.AsyncClient() as client:
            while elapsed < timeout:
                try:
                    resp = await client.get(
                        f"{RENDER_API_BASE}/services/{service_id}/deploys",
                        headers=self._headers(),
                        params={"limit": 1},
                        timeout=10.0,
                    )
                    if resp.status_code == 200:
                        deploys = resp.json()
                        if deploys and len(deploys) > 0:
                            deploy_data = deploys[0]
                            deploy = deploy_data.get("deploy", deploy_data)
                            status = deploy.get("status")
                            logger.debug(f"Service {service_id} deploy status: {status} (elapsed={elapsed}s)")
                            if status == "live":
                                logger.info(f"Service {service_id} deploy is live after {elapsed}s")
                                return True
                            if status in ("build_failed", "update_failed", "canceled"):
                                logger.error(f"Service {service_id} deploy failed: {status}")
                                return False
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    logger.debug(f"Deploy check failed for {service_id}: {e}")

                await asyncio.sleep(interval)
                elapsed += interval

        logger.error(f"Service {service_id} deploy not live after {timeout}s")
        return False

    async def wait_for_service_health(self, health_url: str, timeout: int = 90, interval: int = 3) -> bool:
        """Poll a health endpoint until it responds with 200."""
        elapsed = 0
        logger.info(f"Waiting for health check at {health_url} (timeout={timeout}s)")

        async with httpx.AsyncClient() as client:
            while elapsed < timeout:
                try:
                    resp = await client.get(health_url, timeout=5.0)
                    if resp.status_code == 200:
                        logger.info(f"Service healthy after {elapsed}s")
                        return True
                except (httpx.ConnectError, httpx.TimeoutException):
                    pass

                await asyncio.sleep(interval)
                elapsed += interval

        logger.error(f"Service not healthy after {timeout}s at {health_url}")
        return False

    async def start_service(self, service_id: str, health_url: str, plan: str = "starter") -> bool:
        """Scale, resume, and wait for a service to be ready.

        Returns True if the service is healthy and ready to accept requests.
        """
        if not self.api_key:
            logger.info("Render API key not configured, assuming service is running (local dev)")
            return True

        logger.info(f"Starting service {service_id}: scale → resume → wait")
        await self.scale_service(service_id, plan)
        await self.resume_service(service_id)

        deploy_live = await self.wait_for_deploy_live(service_id, timeout=180, interval=5)
        if not deploy_live:
            return False

        return await self.wait_for_service_health(health_url, timeout=90, interval=3)

    async def stop_service(self, service_id: str) -> bool:
        """Suspend a service after use."""
        if not self.api_key:
            return True
        logger.info(f"Stopping service {service_id}: suspend")
        return await self.suspend_service(service_id)

    async def create_private_service(
        self,
        name: str,
        dockerfile_path: str,
        env_vars: list[dict],
        plan: str = "starter",
        region: str = "virginia",
        branch: str = "staging",
    ) -> Optional[dict]:
        """Create a new private service (pserv) on Render.

        Args:
            name: Service name (e.g. 'cyberx-stepca-1')
            dockerfile_path: Path to Dockerfile in repo (e.g. './Dockerfile.stepca')
            env_vars: List of env var dicts [{"key": "FOO", "value": "bar"}, ...]
            plan: Render plan (default 'starter' = $7/month)
            region: Render region (default 'virginia')
            branch: Git branch to deploy from

        Returns:
            Service dict with 'id' on success, None on failure.
        """
        if not self.api_key:
            logger.error("Render API key not configured, cannot create service")
            return None

        if not self.render_owner_id:
            logger.error("RENDER_OWNER_ID not configured, cannot create service")
            return None

        if not self.render_repo_url:
            logger.error("RENDER_REPO_URL not configured, cannot create service")
            return None

        payload = {
            "type": "private_service",
            "name": name,
            "ownerId": self.render_owner_id,
            "repo": self.render_repo_url,
            "serviceDetails": {
                "plan": plan,
                "region": region,
                "runtime": "docker",
                "envSpecificDetails": {
                    "dockerfilePath": dockerfile_path,
                    "dockerContext": ".",
                },
                "envVars": env_vars,
                "branch": branch,
                "autoDeploy": "no",
            },
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RENDER_API_BASE}/services",
                headers=self._headers(),
                json=payload,
                timeout=60.0,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                service = data.get("service", data)
                service_id = service.get("id")
                logger.info(f"Created Render service '{name}' with ID: {service_id}")
                return service
            else:
                logger.error(f"Failed to create service '{name}': {resp.status_code} {resp.text}")
                return None

    async def delete_service(self, service_id: str) -> bool:
        """Delete a Render service permanently."""
        if not self.api_key:
            logger.error("Render API key not configured, cannot delete service")
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{RENDER_API_BASE}/services/{service_id}",
                headers=self._headers(),
                timeout=30.0,
            )
            if resp.status_code in (200, 204):
                logger.info(f"Deleted Render service {service_id}")
                return True
            else:
                logger.error(f"Failed to delete service {service_id}: {resp.status_code} {resp.text}")
                return False

    async def update_service_env_vars(self, service_id: str, env_vars: list[dict]) -> bool:
        """Update environment variables for a Render service.

        Args:
            service_id: Render service ID
            env_vars: List of env var dicts [{"key": "FOO", "value": "bar"}, ...]
        """
        if not self.api_key:
            return False

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{RENDER_API_BASE}/services/{service_id}/env-vars",
                headers=self._headers(),
                json=env_vars,
                timeout=30.0,
            )
            if resp.status_code in (200, 201):
                logger.info(f"Updated env vars for service {service_id}")
                return True
            else:
                logger.error(f"Failed to update env vars for {service_id}: {resp.status_code} {resp.text}")
                return False
