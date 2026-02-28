"""PowerDNS-Admin API service.

Handles user-account management and zone-account association via the
PowerDNS-Admin REST API. Used by the Keycloak webhook to auto-assign
users to the configured account on first login to PowerDNS-Admin.
"""
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class PowerDNSService:
    """Service for PowerDNS-Admin user/account/zone operations."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.POWERDNS_API_URL.rstrip("/")
        # Derive server API URL from admin URL:
        # "https://host/api/v1/pdnsadmin" → "https://host/api/v1"
        self.server_base_url = self.base_url.rsplit("/pdnsadmin", 1)[0]
        self.auth = httpx.BasicAuth(
            self.settings.POWERDNS_USERNAME,
            self.settings.POWERDNS_PASSWORD,
        )
        self.api_key = self.settings.POWERDNS_API_KEY

    # -------------------------------------------------------------------------
    # Basic Auth methods (user/account CRUD)
    # -------------------------------------------------------------------------

    async def get_user(self, username: str) -> Optional[dict]:
        """Get a PowerDNS-Admin user by username.

        Returns the user dict (includes 'id' and 'accounts') or None if not found.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/users/{username}",
                    auth=self.auth,
                )
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 404:
                    return None
                logger.warning(
                    f"PowerDNS get_user unexpected status: "
                    f"{response.status_code} {response.text}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(f"PowerDNS-Admin unavailable (get_user): {e}")
            return None
        except Exception as e:
            logger.error(f"Error in PowerDNS get_user: {e}")
            return None

    async def get_account(self, name: str) -> Optional[dict]:
        """Get a PowerDNS-Admin account by name.

        Returns the account dict (includes 'id') or None if not found.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/accounts/{name}",
                    auth=self.auth,
                )
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 404:
                    return None
                logger.warning(
                    f"PowerDNS get_account unexpected status: "
                    f"{response.status_code} {response.text}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(f"PowerDNS-Admin unavailable (get_account): {e}")
            return None
        except Exception as e:
            logger.error(f"Error in PowerDNS get_account: {e}")
            return None

    async def create_account(
        self, name: str, description: str = ""
    ) -> Optional[dict]:
        """Create a PowerDNS-Admin account.

        Returns the created account dict, or the existing account if 409.
        Returns None on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/accounts",
                    auth=self.auth,
                    json={"name": name, "description": description},
                )
                if response.status_code == 201:
                    logger.info(f"Created PowerDNS account: {name}")
                    return response.json()
                if response.status_code == 409:
                    # Already exists — fetch and return it
                    logger.info(
                        f"PowerDNS account '{name}' already exists (409)"
                    )
                    return await self.get_account(name)
                logger.error(
                    f"Failed to create PowerDNS account '{name}': "
                    f"{response.status_code} {response.text}"
                )
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(
                f"PowerDNS-Admin unavailable (create_account): {e}"
            )
            return None
        except Exception as e:
            logger.error(f"Error in PowerDNS create_account: {e}")
            return None

    async def add_user_to_account(
        self, account_id: int, user_id: int
    ) -> bool:
        """Add a user to an account.

        Returns True on success (204), False on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(
                    f"{self.base_url}/accounts/{account_id}/users/{user_id}",
                    auth=self.auth,
                )
                if response.status_code == 204:
                    return True
                logger.error(
                    f"Failed to add user {user_id} to account {account_id}: "
                    f"{response.status_code} {response.text}"
                )
                return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(
                f"PowerDNS-Admin unavailable (add_user_to_account): {e}"
            )
            return False
        except Exception as e:
            logger.error(f"Error in PowerDNS add_user_to_account: {e}")
            return False

    # -------------------------------------------------------------------------
    # API Key methods (zone operations via PowerDNS server proxy)
    # -------------------------------------------------------------------------

    async def list_zones(self) -> list[dict]:
        """List all zones from the PowerDNS server (via proxy).

        Uses the API key to call GET /servers/localhost/zones.
        Returns a list of zone dicts (each has 'name', 'account', etc.)
        or an empty list on failure.
        """
        if not self.api_key:
            logger.warning(
                "POWERDNS_API_KEY not configured, cannot list zones"
            )
            return []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.server_base_url}/servers/localhost/zones",
                    headers={"X-API-Key": self.api_key},
                )
                if response.status_code == 200:
                    return response.json()
                logger.error(
                    f"Failed to list zones: "
                    f"{response.status_code} {response.text}"
                )
                return []
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(f"PowerDNS-Admin unavailable (list_zones): {e}")
            return []
        except Exception as e:
            logger.error(f"Error in PowerDNS list_zones: {e}")
            return []

    async def set_zone_account(
        self, zone_name: str, account_name: str
    ) -> bool:
        """Set the account field on a zone.

        Uses the API key to call PUT /servers/localhost/zones/<zone>
        with {"account": account_name}.
        Returns True on success, False on failure.
        """
        if not self.api_key:
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(
                    f"{self.server_base_url}/servers/localhost/zones/{zone_name}",
                    headers={
                        "X-API-Key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={"account": account_name},
                )
                if response.status_code in (200, 204):
                    return True
                logger.warning(
                    f"Failed to set account on zone '{zone_name}': "
                    f"{response.status_code} {response.text}"
                )
                return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(
                f"PowerDNS-Admin unavailable (set_zone_account): {e}"
            )
            return False
        except Exception as e:
            logger.error(f"Error in PowerDNS set_zone_account: {e}")
            return False

    async def associate_all_zones(self, account_name: str) -> dict:
        """Associate all existing zones with the named account.

        Skips zones that already belong to this account.
        Returns {"associated": N, "skipped": N, "failed": N}.
        """
        zones = await self.list_zones()
        if not zones:
            logger.info("No zones found to associate")
            return {"associated": 0, "skipped": 0, "failed": 0}

        associated = 0
        skipped = 0
        failed = 0

        for zone in zones:
            zone_name = zone.get("name", "").rstrip(".")
            current_account = zone.get("account", "")

            if current_account == account_name:
                skipped += 1
                continue

            if await self.set_zone_account(zone_name, account_name):
                associated += 1
            else:
                failed += 1

        logger.info(
            f"Zone association complete: {associated} associated, "
            f"{skipped} skipped, {failed} failed"
        )
        return {
            "associated": associated,
            "skipped": skipped,
            "failed": failed,
        }

    # -------------------------------------------------------------------------
    # High-level orchestration
    # -------------------------------------------------------------------------

    async def ensure_user_in_account(
        self, username: str, account_name: str
    ) -> dict:
        """Ensure a PowerDNS-Admin user belongs to the named account.

        Flow:
        1. GET user by username → get user_id and accounts[]
        2. If user already has accounts → return early
        3. GET-or-CREATE the named account → get account_id
        4. If account was just created, associate all zones with it
        5. PUT user into account

        Returns a dict with 'status' key:
        - "added": user was added to the account
        - "already_member": user already had account(s)
        - "user_not_found": username doesn't exist in PowerDNS-Admin
        - "error": something went wrong
        """
        # Step 1: Get user
        user = await self.get_user(username)
        if user is None:
            logger.info(
                f"PowerDNS user '{username}' not found, "
                f"may not be provisioned yet"
            )
            return {"status": "user_not_found"}

        user_id = user.get("id")
        accounts = user.get("accounts") or []

        # Step 2: Check if user already has accounts
        if accounts:
            account_names = [a.get("name", "") for a in accounts]
            logger.debug(
                f"PowerDNS user '{username}' already in accounts: "
                f"{account_names}"
            )
            return {"status": "already_member", "accounts": account_names}

        # Step 3: Get or create the target account
        account = await self.get_account(account_name)
        account_created = False

        if account is None:
            account = await self.create_account(
                name=account_name,
                description="Auto-created by event management webhook",
            )
            if account is None:
                logger.error(
                    f"Failed to get or create PowerDNS account "
                    f"'{account_name}'"
                )
                return {"status": "error", "detail": "account_unavailable"}
            account_created = True

        account_id = account.get("id")

        # Step 4: If account was just created, associate all zones
        if account_created:
            zone_result = await self.associate_all_zones(account_name)
            logger.info(
                f"Zones associated with new account '{account_name}': "
                f"{zone_result}"
            )

        # Step 5: Add user to account
        if await self.add_user_to_account(account_id, user_id):
            logger.info(
                f"Added PowerDNS user '{username}' (id={user_id}) "
                f"to account '{account_name}' (id={account_id})"
            )
            return {
                "status": "added",
                "user_id": user_id,
                "account_id": account_id,
                "account_created": account_created,
            }

        return {"status": "error", "detail": "add_user_failed"}
