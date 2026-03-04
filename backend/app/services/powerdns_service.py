"""PowerDNS-Admin API service.

Handles user-account management and zone-account association via the
PowerDNS-Admin REST API. Used by the Keycloak webhook to auto-assign
users to the configured account on first login to PowerDNS-Admin.

Also provides domain validation for TLS certificate issuance — verifying
that requested FQDNs correspond to zones that exist in PowerDNS.
"""
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Bare TLDs that cannot have certificates issued for them directly
BARE_TLDS = {
    "com", "net", "org", "biz", "info", "io", "co", "us", "uk", "de", "fr",
    "jp", "cn", "ru", "br", "au", "ca", "in", "it", "es", "nl", "se", "no",
    "fi", "dk", "pl", "cz", "at", "ch", "be", "pt", "ie", "nz", "za", "mx",
    "ar", "cl", "edu", "gov", "mil", "int", "name", "pro", "aero", "coop",
    "museum", "travel", "jobs", "mobi", "cat", "asia", "tel", "xxx", "post",
    "bike", "clothing", "guru", "holdings", "plumbing", "singles", "ventures",
    "today", "technology", "directory", "tips", "voyage", "construction",
    "contractors", "kitchen", "land", "camera", "equipment", "estate",
    "gallery", "graphics", "lighting", "photography", "sexy", "tattoo",
    "buzz", "wiki", "bar", "club", "company", "email", "solutions",
    "support", "training", "recipes", "shoes", "cab", "domains", "limo",
    "maison", "management", "monolithic", "systems", "center", "computer",
}


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
                    headers={"Content-Type": "application/json"},
                    content="{}",
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

    async def get_zone_rrsets(self, zone_name: str) -> list[dict]:
        """Get all RRsets for a zone from the PowerDNS server.

        Uses the API key to call GET /servers/localhost/zones/{zone_name}.
        Returns a list of rrset dicts (each has 'name', 'type', 'records', etc.)
        or an empty list on failure.
        """
        if not self.api_key:
            return []

        # Ensure zone name ends with a dot for the API
        api_zone = zone_name.rstrip(".") + "."

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.server_base_url}/servers/localhost/zones/{api_zone}",
                    headers={"X-API-Key": self.api_key},
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("rrsets", [])
                if response.status_code == 404:
                    return []
                logger.error(
                    f"Failed to get zone '{zone_name}': "
                    f"{response.status_code} {response.text}"
                )
                return []
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.warning(
                f"PowerDNS-Admin unavailable (get_zone_rrsets): {e}"
            )
            return []
        except Exception as e:
            logger.error(f"Error in PowerDNS get_zone_rrsets: {e}")
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

    # -------------------------------------------------------------------------
    # Domain validation for TLS certificate issuance
    # -------------------------------------------------------------------------

    async def validate_domain_for_cert(self, fqdn: str) -> tuple[bool, str]:
        """Validate that an FQDN is eligible for TLS certificate issuance.

        Zones in PowerDNS are bare TLDs (e.g. 'biz', 'com'). Records are
        organized by depth relative to the zone:
          depth 0 = zone apex (biz)
          depth 1 = direct child (test.biz)
          depth 2 = sub-child (www.test.biz)

        Rules:
        1. FQDN must have at least 2 labels (e.g. 'test.biz', not 'biz')
        2. A parent zone must exist in PowerDNS
        3. Non-wildcard: exact DNS record must exist (e.g. 'test.biz')
        4. Wildcard (*.test.biz): any record under the depth-1 label 'test'
           proves the participant owns that domain space — accepts test.biz,
           www.test.biz, mail.test.biz, etc.
        5. *.biz (bare TLD wildcard) is blocked by the 2-label check

        Returns:
            Tuple of (is_valid, error_message). error_message is empty if valid.
        """
        clean = fqdn.strip().rstrip(".")

        # Strip wildcard prefix for validation
        check_domain = clean
        if check_domain.startswith("*."):
            check_domain = check_domain[2:]

        parts = check_domain.split(".")
        if len(parts) < 2:
            return False, "Domain must have at least two labels (e.g. example.com)"

        if check_domain.lower() in BARE_TLDS:
            return False, f"Cannot issue certificate for bare TLD '{check_domain}'"

        # Check if any parent zone exists in PowerDNS
        zones = await self.list_zones()
        if not zones:
            return False, "Unable to connect to PowerDNS or no zones configured"

        zone_names = {z.get("name", "").rstrip(".").lower() for z in zones}
        logger.debug(
            f"Domain validation: fqdn='{fqdn}', check_domain='{check_domain}', "
            f"zone_names={zone_names}"
        )

        # Find the matching parent zone
        matched_zone = None
        for i in range(len(parts)):
            candidate = ".".join(parts[i:]).lower()
            if candidate in zone_names:
                matched_zone = candidate
                break

        if not matched_zone:
            return False, f"No matching zone found in PowerDNS for '{fqdn}'"

        # Verify DNS records exist within the zone
        rrsets = await self.get_zone_rrsets(matched_zone)
        if not rrsets:
            return False, f"Zone '{matched_zone}' has no records or is unreachable"

        # Build set of record names (PowerDNS uses trailing dot, strip it)
        zone_suffix = "." + matched_zone + "."
        record_names = {r.get("name", "").lower() for r in rrsets}
        logger.debug(
            f"Record validation: check_domain='{check_domain}', "
            f"is_wildcard={clean.startswith('*.')}, records={record_names}"
        )

        is_wildcard = clean.startswith("*.")
        base_name = check_domain.lower().rstrip(".") + "."

        # For non-wildcard requests, check for an exact record match
        if not is_wildcard:
            if base_name in record_names:
                return True, ""
            return False, (
                f"No DNS record found for '{check_domain}' in zone "
                f"'{matched_zone}'. Create the record in PowerDNS first."
            )

        # For wildcard requests (e.g. *.test.biz with zone 'biz'):
        # Organize records by depth relative to the zone.
        #   depth 0 = zone apex (biz.)
        #   depth 1 = direct child (test.biz.)
        #   depth 2 = sub-child (www.test.biz.)
        # The wildcard base domain (test.biz) is at depth 1.
        # Accept the wildcard if ANY record exists under that depth-1 label,
        # i.e. the base domain itself (test.biz.) or any sub-record (www.test.biz.).
        wildcard_base_label = check_domain.split(".")[0].lower()  # e.g. "test"

        for name in record_names:
            # Strip zone suffix to get the relative part
            if not name.endswith(zone_suffix):
                continue
            relative = name[: -len(zone_suffix)]  # e.g. "test" or "www.test"
            if not relative:
                continue  # depth 0 (zone apex), skip

            # Check if this record's depth-1 label matches the wildcard base
            rel_parts = relative.split(".")
            depth1_label = rel_parts[-1]  # rightmost label = depth 1
            if depth1_label == wildcard_base_label:
                logger.debug(
                    f"Wildcard validated: record '{name}' matches "
                    f"depth-1 label '{wildcard_base_label}'"
                )
                return True, ""

        return False, (
            f"No DNS records found under '{check_domain}' in zone "
            f"'{matched_zone}'. Create at least one record (e.g. "
            f"'{check_domain}' or 'www.{check_domain}') in PowerDNS first."
        )
