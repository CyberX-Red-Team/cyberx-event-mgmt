"""Keycloak credential sync service.

Manages an encrypted queue of credential changes that need to be pushed
to Keycloak when it becomes available. Supports create, update, and delete
operations with retry logic.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.password_sync_queue import PasswordSyncQueue, SyncOperation
from app.models.user import User
from app.utils.encryption import encrypt_field, decrypt_field

logger = logging.getLogger(__name__)


class KeycloakSyncService:
    """Service for syncing user credentials to Keycloak."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = get_settings()

    async def queue_user_sync(
        self,
        user_id: int,
        username: str,
        password: Optional[str],
        operation: SyncOperation
    ):
        """
        Queue a credential sync operation for Keycloak.

        For CREATE_USER and UPDATE_PASSWORD, the password is encrypted
        before storage. For DELETE_USER, password is not needed.

        If an unsynced entry already exists for this user, it is updated
        (upsert) to avoid duplicate queue entries.
        """
        encrypted_password = None
        if password and operation != SyncOperation.DELETE_USER:
            encrypted_password = encrypt_field(password)

        # Check for existing unsynced entry for this user
        result = await self.session.execute(
            select(PasswordSyncQueue).where(
                PasswordSyncQueue.user_id == user_id,
                PasswordSyncQueue.synced == False
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.username = username
            existing.encrypted_password = encrypted_password
            existing.operation = operation.value
            existing.retry_count = 0
            existing.last_error = None
            existing.created_at = datetime.now(timezone.utc)
            logger.info(
                f"Updated existing sync queue entry for user {user_id} "
                f"(operation: {operation.value})"
            )
        else:
            entry = PasswordSyncQueue(
                user_id=user_id,
                username=username,
                encrypted_password=encrypted_password,
                operation=operation.value
            )
            self.session.add(entry)
            logger.info(
                f"Queued sync operation for user {user_id} "
                f"(operation: {operation.value})"
            )

    async def process_sync_queue(self) -> dict:
        """
        Process all pending sync queue entries.

        Attempts to push each entry to Keycloak. On success, marks as synced
        and updates the user's keycloak_synced flag. On failure, increments
        retry count.

        Returns:
            Dict with synced/failed/skipped counts.
        """
        max_retries = self.settings.PASSWORD_SYNC_MAX_RETRIES

        result = await self.session.execute(
            select(PasswordSyncQueue).where(
                PasswordSyncQueue.synced == False,
                PasswordSyncQueue.retry_count < max_retries
            ).order_by(PasswordSyncQueue.created_at)
        )
        pending = result.scalars().all()

        if not pending:
            return {"synced": 0, "failed": 0, "skipped": 0}

        # Pre-flight: check if Keycloak is reachable
        keycloak_available = await self.check_keycloak_health()
        if not keycloak_available:
            logger.warning("Keycloak is not reachable - skipping sync processing")
            return {"synced": 0, "failed": 0, "skipped": len(pending)}

        # Get admin token once for all operations
        try:
            admin_token = await self._get_admin_token()
        except Exception as e:
            logger.error(f"Failed to get Keycloak admin token: {e}")
            return {"synced": 0, "failed": 0, "skipped": len(pending)}

        synced_count = 0
        failed_count = 0

        for entry in pending:
            try:
                success = await self._sync_entry(entry, admin_token)

                if success:
                    entry.synced = True
                    entry.synced_at = datetime.now(timezone.utc)
                    synced_count += 1

                    # Update user's keycloak_synced flag
                    if entry.operation != SyncOperation.DELETE_USER.value:
                        user_result = await self.session.execute(
                            select(User).where(User.id == entry.user_id)
                        )
                        user = user_result.scalar_one_or_none()
                        if user:
                            user.keycloak_synced = True

                    logger.info(
                        f"Synced {entry.operation} for user {entry.user_id} "
                        f"({entry.username})"
                    )
                else:
                    entry.retry_count += 1
                    entry.last_error = "Keycloak API returned non-success"
                    failed_count += 1

            except Exception as e:
                entry.retry_count += 1
                entry.last_error = str(e)[:500]
                failed_count += 1
                logger.error(
                    f"Failed to sync {entry.operation} for user {entry.user_id}: {e}"
                )

        await self.session.commit()

        logger.info(
            f"Sync queue processing complete: "
            f"{synced_count} synced, {failed_count} failed"
        )
        return {"synced": synced_count, "failed": failed_count, "skipped": 0}

    async def _sync_entry(self, entry: PasswordSyncQueue, admin_token: str) -> bool:
        """
        Sync a single queue entry to Keycloak.

        Routes to the appropriate Keycloak Admin API call based on operation type.
        """
        if entry.operation == SyncOperation.CREATE_USER.value:
            return await self._create_keycloak_user(entry, admin_token)
        elif entry.operation == SyncOperation.UPDATE_PASSWORD.value:
            return await self._update_keycloak_password(entry, admin_token)
        elif entry.operation == SyncOperation.DELETE_USER.value:
            return await self._delete_keycloak_user(entry, admin_token)
        else:
            logger.error(f"Unknown sync operation: {entry.operation}")
            return False

    async def _create_keycloak_user(
        self, entry: PasswordSyncQueue, admin_token: str
    ) -> bool:
        """Create a user in Keycloak with credentials."""
        password = decrypt_field(entry.encrypted_password) if entry.encrypted_password else None

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Check if user already exists
            existing_id = await self._find_keycloak_user(client, admin_token, entry.username)

            if existing_id:
                # User exists — just update password
                if password:
                    return await self._set_keycloak_password(
                        client, admin_token, existing_id, password
                    )
                return True

            # Create new user
            user_payload = {
                "username": entry.username,
                "enabled": True,
                "credentials": []
            }

            if password:
                user_payload["credentials"].append({
                    "type": "password",
                    "value": password,
                    "temporary": False
                })

            response = await client.post(
                f"{self.settings.KEYCLOAK_URL}/admin/realms/"
                f"{self.settings.KEYCLOAK_REALM}/users",
                headers={"Authorization": f"Bearer {admin_token}"},
                json=user_payload
            )

            if response.status_code == 201:
                return True
            elif response.status_code == 409:
                # Conflict — user already exists (race condition), update password instead
                logger.info(f"User {entry.username} already exists in Keycloak, updating password")
                kc_user_id = await self._find_keycloak_user(client, admin_token, entry.username)
                if kc_user_id and password:
                    return await self._set_keycloak_password(
                        client, admin_token, kc_user_id, password
                    )
                return True
            else:
                logger.error(
                    f"Failed to create Keycloak user {entry.username}: "
                    f"{response.status_code} {response.text}"
                )
                return False

    async def _update_keycloak_password(
        self, entry: PasswordSyncQueue, admin_token: str
    ) -> bool:
        """Update a user's password in Keycloak."""
        password = decrypt_field(entry.encrypted_password) if entry.encrypted_password else None
        if not password:
            logger.error(f"No password to sync for user {entry.username}")
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            kc_user_id = await self._find_keycloak_user(client, admin_token, entry.username)

            if not kc_user_id:
                # User doesn't exist yet — create them instead
                logger.info(
                    f"User {entry.username} not found in Keycloak, creating instead"
                )
                entry.operation = SyncOperation.CREATE_USER.value
                return await self._create_keycloak_user(entry, admin_token)

            return await self._set_keycloak_password(
                client, admin_token, kc_user_id, password
            )

    async def _delete_keycloak_user(
        self, entry: PasswordSyncQueue, admin_token: str
    ) -> bool:
        """Delete a user from Keycloak."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            kc_user_id = await self._find_keycloak_user(client, admin_token, entry.username)

            if not kc_user_id:
                # User doesn't exist — nothing to delete
                logger.info(f"User {entry.username} not found in Keycloak, nothing to delete")
                return True

            response = await client.delete(
                f"{self.settings.KEYCLOAK_URL}/admin/realms/"
                f"{self.settings.KEYCLOAK_REALM}/users/{kc_user_id}",
                headers={"Authorization": f"Bearer {admin_token}"}
            )

            if response.status_code == 204:
                return True
            else:
                logger.error(
                    f"Failed to delete Keycloak user {entry.username}: "
                    f"{response.status_code} {response.text}"
                )
                return False

    async def _set_keycloak_password(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        kc_user_id: str,
        password: str
    ) -> bool:
        """Set a user's password in Keycloak."""
        response = await client.put(
            f"{self.settings.KEYCLOAK_URL}/admin/realms/"
            f"{self.settings.KEYCLOAK_REALM}/users/{kc_user_id}/reset-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "type": "password",
                "value": password,
                "temporary": False
            }
        )

        if response.status_code == 204:
            return True
        else:
            logger.error(
                f"Failed to set password for Keycloak user {kc_user_id}: "
                f"{response.status_code} {response.text}"
            )
            return False

    async def _get_admin_token(self) -> str:
        """Get Keycloak admin access token via client credentials grant."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.settings.KEYCLOAK_URL}/realms/master/"
                f"protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.KEYCLOAK_ADMIN_CLIENT_ID,
                    "client_secret": self.settings.KEYCLOAK_ADMIN_CLIENT_SECRET
                }
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Failed to get admin token: {response.status_code} {response.text}"
                )

            data = response.json()
            return data["access_token"]

    async def _find_keycloak_user(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        username: str
    ) -> Optional[str]:
        """Find a Keycloak user ID by username. Returns None if not found."""
        response = await client.get(
            f"{self.settings.KEYCLOAK_URL}/admin/realms/"
            f"{self.settings.KEYCLOAK_REALM}/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"username": username, "exact": "true"}
        )

        if response.status_code != 200:
            logger.error(f"Failed to search Keycloak users: {response.status_code}")
            return None

        users = response.json()
        if not users:
            return None

        return users[0]["id"]

    async def check_keycloak_health(self) -> bool:
        """Check if Keycloak is reachable."""
        if not self.settings.KEYCLOAK_URL:
            return False

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.settings.KEYCLOAK_URL}/realms/"
                    f"{self.settings.KEYCLOAK_REALM}"
                )
                return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def get_queue_stats(self) -> dict:
        """Get sync queue statistics for admin dashboard."""
        max_retries = self.settings.PASSWORD_SYNC_MAX_RETRIES

        result = await self.session.execute(
            select(
                func.count(PasswordSyncQueue.id).label('total'),
                func.sum(
                    case((PasswordSyncQueue.synced == True, 1), else_=0)
                ).label('synced'),
                func.sum(
                    case(
                        (
                            (PasswordSyncQueue.synced == False) &
                            (PasswordSyncQueue.retry_count < max_retries),
                            1
                        ),
                        else_=0
                    )
                ).label('pending'),
                func.sum(
                    case(
                        (
                            (PasswordSyncQueue.synced == False) &
                            (PasswordSyncQueue.retry_count >= max_retries),
                            1
                        ),
                        else_=0
                    )
                ).label('failed'),
            )
        )
        stats = result.first()

        # Get failed entries for detail
        failed_result = await self.session.execute(
            select(PasswordSyncQueue).where(
                PasswordSyncQueue.synced == False,
                PasswordSyncQueue.retry_count >= max_retries
            ).order_by(PasswordSyncQueue.created_at.desc())
        )
        failed_entries = failed_result.scalars().all()

        return {
            "total": stats.total or 0,
            "synced": stats.synced or 0,
            "pending": stats.pending or 0,
            "failed": stats.failed or 0,
            "failed_entries": [
                {
                    "id": e.id,
                    "user_id": e.user_id,
                    "username": e.username,
                    "operation": e.operation,
                    "retry_count": e.retry_count,
                    "last_error": e.last_error,
                    "created_at": e.created_at.isoformat() if e.created_at else None
                }
                for e in failed_entries
            ]
        }
