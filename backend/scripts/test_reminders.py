"""
Test script for triggering invitation reminder emails.

Authenticates to the admin API and provides commands for:
- Dry-run preview of eligible users per stage
- Triggering specific stages (1, 2, 3) or all stages
- Targeting specific users by ID
- Force re-sending reminders
- Checking email queue status after triggering

Usage:
    # Against local dev server (default)
    python scripts/test_reminders.py

    # Against staging
    python scripts/test_reminders.py --base-url https://staging.events.cyberxredteam.org

    # Dry run for stage 1 only
    python scripts/test_reminders.py --stage 1 --dry-run

    # Force send stage 2 to specific users
    python scripts/test_reminders.py --stage 2 --user-ids 12,34 --force

    # Send all stages (no dry run)
    python scripts/test_reminders.py --send
"""
import argparse
import asyncio
import json
import sys

import httpx


DEFAULT_BASE = "http://localhost:8000"
DEFAULT_USERNAME = "admin@cyberxredteam.org"


async def get_csrf_and_login(
    client: httpx.AsyncClient, base_url: str, username: str, password: str
) -> bool:
    """Fetch CSRF token and log in. Returns True on success."""
    # Step 1: Hit the home page to get a CSRF cookie
    print("   Fetching CSRF token...")
    resp = await client.get(f"{base_url}/")
    csrf_token = resp.cookies.get("csrf_token")
    if not csrf_token:
        # Try extracting from all cookies (sometimes it's set on a redirect)
        for cookie in client.cookies.jar:
            if cookie.name == "csrf_token":
                csrf_token = cookie.value
                break

    if not csrf_token:
        print("   ❌ Could not obtain CSRF token from cookies")
        return False
    print(f"   CSRF token: {csrf_token[:16]}...")

    # Step 2: Login
    print(f"   Logging in as {username}...")
    resp = await client.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
        headers={"X-CSRF-Token": csrf_token},
    )
    if resp.status_code != 200:
        print(f"   ❌ Login failed: {resp.status_code}")
        print(f"   {resp.text}")
        return False

    data = resp.json()
    print(f"   ✅ Logged in as {data.get('username', username)} (role: {data.get('role', '?')})")

    # Store CSRF for subsequent requests
    client.headers["X-CSRF-Token"] = csrf_token
    return True


async def trigger_reminders(
    client: httpx.AsyncClient,
    base_url: str,
    stage: int | None = None,
    user_ids: str | None = None,
    force: bool = False,
    dry_run: bool = True,
    skip_checks: bool = False,
) -> dict | None:
    """Call POST /api/admin/reminders/trigger and return the response."""
    params = {}
    if stage is not None:
        params["stage"] = stage
    if user_ids:
        params["user_ids"] = user_ids
    if force:
        params["force"] = "true"
    if dry_run:
        params["dry_run"] = "true"
    if skip_checks:
        params["skip_checks"] = "true"

    label = "DRY RUN" if dry_run else "LIVE SEND"
    stage_label = f"stage {stage}" if stage else "all stages"
    print(f"\n📨 Triggering reminders ({label}) — {stage_label}")
    if user_ids:
        print(f"   Targeting user IDs: {user_ids}")
    if force:
        print("   Force mode: re-sending even if already sent")
    if skip_checks:
        print("   Skip checks: bypassing invitation/status requirements")

    resp = await client.post(
        f"{base_url}/api/admin/reminders/trigger",
        params=params,
    )

    if resp.status_code != 200:
        print(f"   ❌ Trigger failed: {resp.status_code}")
        print(f"   {resp.text}")
        return None

    data = resp.json()
    return data


def print_trigger_results(data: dict):
    """Pretty-print the trigger response."""
    print(f"\n{'=' * 60}")
    print(f"  Event:           {data['event']}")
    print(f"  Test mode:       {data['test_mode']}")
    print(f"  Days until event: {data['days_until_event']}")
    print(f"  Dry run:         {data['dry_run']}")
    print(f"  Force:           {data['force']}")
    print(f"{'=' * 60}")

    results = data.get("results", {})
    if not results:
        print("\n  No stages processed.")
        return

    for stage_key in sorted(results.keys()):
        stage_data = results[stage_key]
        stage_num = stage_key.replace("stage_", "")
        print(f"\n  Stage {stage_num}:")

        if data["dry_run"]:
            count = stage_data.get("eligible_count", 0)
            would_send = stage_data.get("would_send", False)
            print(f"    Eligible users: {count}")
            print(f"    Would send:     {would_send}")
            users = stage_data.get("users", [])
        else:
            queued = stage_data.get("queued", 0)
            print(f"    Queued: {queued}")
            users = stage_data.get("users", [])

        if users:
            print(f"    Users:")
            for u in users:
                name = u.get("name", "")
                line = f"      - ID {u['id']:>4}: {u['email']}"
                if name:
                    line += f" ({name})"
                print(line)
        else:
            print(f"    Users: (none)")

    print()


async def check_queue_stats(client: httpx.AsyncClient, base_url: str):
    """Fetch and display email queue stats."""
    print("\n📊 Email Queue Stats")
    resp = await client.get(f"{base_url}/api/admin/email-queue/stats")
    if resp.status_code != 200:
        print(f"   ❌ Could not fetch queue stats: {resp.status_code}")
        return

    data = resp.json()
    print(f"   Pending:    {data.get('pending', '?')}")
    print(f"   Processing: {data.get('processing', '?')}")
    print(f"   Sent:       {data.get('sent', '?')}")
    print(f"   Failed:     {data.get('failed', '?')}")
    print(f"   Cancelled:  {data.get('cancelled', '?')}")


async def list_recent_queue(client: httpx.AsyncClient, base_url: str, limit: int = 10):
    """Show recent items in the email queue."""
    print(f"\n📬 Recent Email Queue Entries (last {limit})")
    resp = await client.get(
        f"{base_url}/api/admin/email-queue",
        params={"page": 1, "page_size": limit, "sort_by": "created_at", "sort_dir": "desc"},
    )
    if resp.status_code != 200:
        print(f"   ❌ Could not fetch queue: {resp.status_code}")
        return

    data = resp.json()
    items = data.get("items", [])
    if not items:
        print("   (empty queue)")
        return

    for item in items:
        status = item.get("status", "?")
        template = item.get("template_name", "?")
        user_email = item.get("user_email", item.get("user_id", "?"))
        created = item.get("created_at", "?")
        if isinstance(created, str) and len(created) > 19:
            created = created[:19]
        print(f"   [{status:>10}] {template:<30} → {user_email:<35} ({created})")


async def main():
    parser = argparse.ArgumentParser(description="Test invitation reminder triggering")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help=f"API base URL (default: {DEFAULT_BASE})")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help=f"Admin username (default: {DEFAULT_USERNAME})")
    parser.add_argument("--password", default=None, help="Admin password (will prompt if not provided)")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3], default=None, help="Reminder stage (1, 2, or 3). Omit for all.")
    parser.add_argument("--user-ids", default=None, help="Comma-separated user IDs to target")
    parser.add_argument("--force", action="store_true", help="Re-send even if already sent for this stage")
    parser.add_argument("--skip-checks", action="store_true", help="Skip confirmation_sent_at and participation status checks")
    parser.add_argument("--send", action="store_true", help="Actually send (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default)")
    parser.add_argument("--queue-stats", action="store_true", help="Also show email queue stats")
    parser.add_argument("--queue-recent", type=int, default=0, metavar="N", help="Show N most recent queue entries")
    parser.add_argument("--json", action="store_true", help="Output raw JSON response")
    args = parser.parse_args()

    # --send flips dry_run off
    dry_run = not args.send

    # Prompt for password if not provided
    password = args.password
    if not password:
        import getpass
        password = getpass.getpass(f"Password for {args.username}: ")

    print(f"\n🔧 Reminder Test Script")
    print(f"   Target: {args.base_url}")
    print(f"   Mode:   {'DRY RUN (preview only)' if dry_run else '⚡ LIVE SEND'}")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        # Authenticate
        print(f"\n🔐 Authentication")
        if not await get_csrf_and_login(client, args.base_url, args.username, password):
            sys.exit(1)

        # Trigger reminders
        data = await trigger_reminders(
            client,
            args.base_url,
            stage=args.stage,
            user_ids=args.user_ids,
            force=args.force,
            dry_run=dry_run,
            skip_checks=args.skip_checks,
        )

        if data is None:
            sys.exit(1)

        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print_trigger_results(data)

        # Optional: queue stats
        if args.queue_stats or not dry_run:
            await check_queue_stats(client, args.base_url)

        # Optional: recent queue entries
        if args.queue_recent > 0 or not dry_run:
            n = args.queue_recent if args.queue_recent > 0 else 10
            await list_recent_queue(client, args.base_url, limit=n)

    print("✅ Done\n")


if __name__ == "__main__":
    asyncio.run(main())
