"""
Clone and rename the system Sponsor and Invitee roles via the platform API.

Usage:
    python scripts/clone_roles.py --api-url URL --sponsor-name NAME --invitee-name NAME

Examples:
    python scripts/clone_roles.py \
        --api-url https://staging.events.cyberxredteam.org \
        --sponsor-name "CyberX 2026 Sponsor" \
        --invitee-name "CyberX 2026 Invitee"
"""

import argparse
import getpass
import sys

import requests


class APIClient:
    """Thin wrapper around the platform API."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def _ensure_csrf(self) -> None:
        if "X-CSRF-Token" in self.session.headers:
            return
        self.session.get(f"{self.base_url}/api/public/countries")
        csrf = self.session.cookies.get("csrf_token")
        if csrf:
            self.session.headers["X-CSRF-Token"] = csrf

    def login(self, username: str, password: str) -> dict:
        self._ensure_csrf()
        resp = self.session.post(
            f"{self.base_url}/api/auth/login",
            json={"username": username, "password": password},
        )
        resp.raise_for_status()
        return resp.json()

    def get_roles(self) -> list[dict]:
        resp = self.session.get(f"{self.base_url}/api/admin/roles/")
        resp.raise_for_status()
        return resp.json()

    def clone_role(self, role_id: int) -> dict:
        self._ensure_csrf()
        resp = self.session.post(f"{self.base_url}/api/admin/roles/{role_id}/clone")
        resp.raise_for_status()
        return resp.json()

    def rename_role(self, role_id: int, new_name: str) -> dict:
        self._ensure_csrf()
        resp = self.session.put(
            f"{self.base_url}/api/admin/roles/{role_id}",
            json={"name": new_name},
        )
        resp.raise_for_status()
        return resp.json()


def find_system_role(roles: list[dict], base_type: str) -> dict | None:
    """Find the system role for a given base_type."""
    for r in roles:
        if r.get("base_type") == base_type and r.get("is_system"):
            return r
    return None


def print_permissions(label: str, role: dict) -> None:
    """Print a role's permissions."""
    perms = role.get("permissions", [])
    print(f"\n  {label}: '{role['name']}' (id={role['id']}) — {len(perms)} permissions")
    if perms:
        for p in perms:
            print(f"    - {p}")
    else:
        print("    (none)")


def main():
    parser = argparse.ArgumentParser(description="Clone and rename Sponsor/Invitee roles")
    parser.add_argument("--api-url", type=str, required=True, help="Base URL of the platform API")
    parser.add_argument("--sponsor-name", type=str, required=True, help="Name for the cloned sponsor role")
    parser.add_argument("--invitee-name", type=str, required=True, help="Name for the cloned invitee role")
    args = parser.parse_args()

    print("CyberX Role Cloner")
    print("=" * 60)

    api = APIClient(args.api_url)

    # Login
    username = input("Admin email or username: ")
    password = getpass.getpass("Admin password: ")
    try:
        result = api.login(username, password)
        print(f"Logged in as: {result.get('user', {}).get('email', username)}")
    except requests.exceptions.HTTPError as e:
        print(f"Login failed: {e}")
        sys.exit(1)

    # Fetch roles
    print("\nFetching existing roles...")
    roles = api.get_roles()
    for r in roles:
        system = " [system]" if r.get("is_system") else ""
        print(f"  - {r['name']} (base_type={r['base_type']}, id={r['id']}){system}")

    sponsor_role = find_system_role(roles, "sponsor")
    invitee_role = find_system_role(roles, "invitee")

    if not sponsor_role:
        print("ERROR: System sponsor role not found")
        sys.exit(1)
    if not invitee_role:
        print("ERROR: System invitee role not found")
        sys.exit(1)

    # --- Sponsor ---
    print(f"\n{'=' * 60}")
    print("SPONSOR ROLE")
    print_permissions("Original", sponsor_role)

    print(f"\n  Cloning '{sponsor_role['name']}' (id={sponsor_role['id']})...")
    cloned_sponsor = api.clone_role(sponsor_role["id"])
    renamed_sponsor = api.rename_role(cloned_sponsor["id"], args.sponsor_name)
    print_permissions("Clone", renamed_sponsor)

    # --- Invitee ---
    print(f"\n{'=' * 60}")
    print("INVITEE ROLE")
    print_permissions("Original", invitee_role)

    print(f"\n  Cloning '{invitee_role['name']}' (id={invitee_role['id']})...")
    cloned_invitee = api.clone_role(invitee_role["id"])
    renamed_invitee = api.rename_role(cloned_invitee["id"], args.invitee_name)
    print_permissions("Clone", renamed_invitee)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print("Done! New roles created:")
    print(f"  Sponsor: '{renamed_sponsor['name']}' (id={renamed_sponsor['id']}, slug={renamed_sponsor['slug']})")
    print(f"  Invitee: '{renamed_invitee['name']}' (id={renamed_invitee['id']}, slug={renamed_invitee['slug']})")
    print(f"\nUse these role IDs in the import script when prompted.")


if __name__ == "__main__":
    main()
