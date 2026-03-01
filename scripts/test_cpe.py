#!/usr/bin/env python3
"""
Test script for CPE Certificate System against staging environment.

Usage:
    python scripts/test_cpe.py --email admin@example.com --password 'yourpassword'

Optional:
    --base-url https://staging.events.cyberxredteam.org  (default)
    --event-id 1            (default)
    --target-email EMAIL    (issue cert for this user; default: self)
    --render-api-key KEY    (Render API key for Gotenberg lifecycle)
    --gotenberg-service-id ID  (Render service ID for Gotenberg)
"""
import argparse
import json
import sys
import time

import requests


RENDER_API_BASE = "https://api.render.com/v1"


def print_step(n, desc):
    print(f"\n{'='*60}")
    print(f"  Step {n}: {desc}")
    print(f"{'='*60}")


def print_result(label, data):
    print(f"\n  {label}:")
    if isinstance(data, dict):
        print(json.dumps(data, indent=4, default=str))
    else:
        print(f"  {data}")


# ---------------------------------------------------------------
# Render API helpers
# ---------------------------------------------------------------

def render_scale_gotenberg(api_key, service_id, plan="standard"):
    """Scale Gotenberg to the specified plan."""
    print(f"  Scaling Gotenberg to '{plan}' plan...")
    resp = requests.patch(
        f"{RENDER_API_BASE}/services/{service_id}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={"plan": plan},
        timeout=30,
    )
    if resp.status_code == 200:
        print(f"  Scaled to {plan}")
        return True
    else:
        print(f"  Scale failed: {resp.status_code} {resp.text}")
        return False


def render_resume_gotenberg(api_key, service_id):
    """Resume Gotenberg service."""
    print("  Resuming Gotenberg service...")
    resp = requests.post(
        f"{RENDER_API_BASE}/services/{service_id}/resume",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        timeout=30,
    )
    if resp.status_code in (200, 202):
        print("  Resume requested")
        return True
    else:
        print(f"  Resume failed: {resp.status_code} {resp.text}")
        return False


def render_suspend_gotenberg(api_key, service_id):
    """Suspend Gotenberg service."""
    print("  Suspending Gotenberg service...")
    resp = requests.post(
        f"{RENDER_API_BASE}/services/{service_id}/suspend",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        timeout=30,
    )
    if resp.status_code in (200, 202):
        print("  Suspended")
        return True
    else:
        print(f"  Suspend failed: {resp.status_code} {resp.text}")
        return False


def render_wait_for_gotenberg(gotenberg_url, timeout=120, interval=5):
    """Poll Gotenberg health endpoint until ready."""
    health_url = f"{gotenberg_url}/health"
    print(f"  Waiting for Gotenberg at {health_url} (timeout={timeout}s)...")
    elapsed = 0
    while elapsed < timeout:
        try:
            resp = requests.get(health_url, timeout=5)
            if resp.status_code == 200:
                print(f"  Gotenberg ready after {elapsed}s")
                return True
        except requests.ConnectionError:
            pass
        except requests.Timeout:
            pass
        time.sleep(interval)
        elapsed += interval
        if elapsed % 15 == 0:
            print(f"  Still waiting... ({elapsed}s)")
    print(f"  Gotenberg not ready after {timeout}s")
    return False


def start_gotenberg(api_key, service_id, gotenberg_url):
    """Scale to standard, resume, and wait for Gotenberg."""
    render_scale_gotenberg(api_key, service_id, "standard")
    render_resume_gotenberg(api_key, service_id)
    return render_wait_for_gotenberg(gotenberg_url)


def stop_gotenberg(api_key, service_id):
    """Suspend Gotenberg."""
    render_suspend_gotenberg(api_key, service_id)


def main():
    parser = argparse.ArgumentParser(description="Test CPE Certificate System")
    parser.add_argument("--base-url", default="https://staging.events.cyberxredteam.org")
    parser.add_argument("--email", required=True, help="Admin email")
    parser.add_argument("--password", required=True, help="Admin password")
    parser.add_argument("--event-id", type=int, default=1, help="Event ID to test with")
    parser.add_argument("--target-email", default=None,
                        help="Email of user to issue cert for (default: self)")
    parser.add_argument("--render-api-key", default=None,
                        help="Render API key for Gotenberg lifecycle management")
    parser.add_argument("--gotenberg-service-id", default=None,
                        help="Render service ID for Gotenberg")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    session = requests.Session()
    render_enabled = bool(args.render_api_key and args.gotenberg_service_id)

    if render_enabled:
        print("  Render API integration enabled for Gotenberg lifecycle management")
    else:
        print("  Render API not configured (--render-api-key / --gotenberg-service-id)")
        print("  Gotenberg must be running manually for PDF tests")

    # ---------------------------------------------------------------
    # Step 1: Get a CSRF token (any GET sets the cookie)
    # ---------------------------------------------------------------
    print_step(1, "Fetching CSRF token")
    resp = session.get(f"{base}/health")
    print(f"  Health check: {resp.status_code}")

    csrf_token = session.cookies.get("csrf_token")
    if not csrf_token:
        print("  ERROR: No csrf_token cookie received. Check if the server is up.")
        sys.exit(1)
    print(f"  CSRF token: {csrf_token[:20]}...")

    headers = {
        "X-CSRF-Token": csrf_token,
        "Content-Type": "application/json",
    }

    # ---------------------------------------------------------------
    # Step 2: Login as admin
    # ---------------------------------------------------------------
    print_step(2, "Logging in as admin")
    resp = session.post(f"{base}/api/auth/login", json={
        "username": args.email,
        "password": args.password,
    }, headers=headers)

    if resp.status_code != 200:
        print(f"  ERROR: Login failed ({resp.status_code})")
        print(f"  {resp.text}")
        sys.exit(1)

    login_data = resp.json()
    admin_user_id = login_data.get("user", {}).get("id")
    user_info = login_data.get("user", {})
    print(f"  Logged in as: {user_info.get('email')}")
    print(f"  Admin user ID: {admin_user_id}")
    print(f"  Is admin: {user_info.get('is_admin')}")

    # Refresh CSRF token (login response may set a new one)
    csrf_token = session.cookies.get("csrf_token", csrf_token)
    headers["X-CSRF-Token"] = csrf_token

    event_id = args.event_id

    # ---------------------------------------------------------------
    # Step 2b: Resolve target user by email
    # ---------------------------------------------------------------
    target_email = args.target_email
    if target_email:
        print(f"\n  Resolving target user: {target_email}")
        resp = session.get(
            f"{base}/api/admin/participants",
            params={"search": target_email, "page_size": 5},
            headers=headers,
        )
        if resp.status_code != 200:
            print(f"  ERROR: Failed to search participants ({resp.status_code})")
            print(f"  {resp.text}")
            sys.exit(1)

        data = resp.json()
        participants = data.get("items", data.get("participants", []))
        match = None
        for p in participants:
            if p.get("email", "").lower() == target_email.lower():
                match = p
                break

        if not match:
            print(f"  ERROR: No participant found with email '{target_email}'")
            if participants:
                print(f"  Search returned {len(participants)} results:")
                for p in participants:
                    print(f"    - {p.get('email')} (id={p.get('id')})")
            sys.exit(1)

        user_id = match["id"]
        print(f"  Found: {match.get('first_name')} {match.get('last_name')} "
              f"({match.get('email')}) - ID: {user_id}")
    else:
        user_id = admin_user_id
        print(f"\n  No --target-email specified, using self (user ID: {user_id})")

    # ---------------------------------------------------------------
    # Step 3: Check eligibility for a single user
    # ---------------------------------------------------------------
    print_step(3, f"Checking eligibility for user {user_id}, event {event_id}")
    resp = session.get(
        f"{base}/api/admin/cpe/eligibility/{event_id}/{user_id}",
        headers=headers,
    )
    if resp.status_code == 200:
        print_result("Eligibility", resp.json())
    else:
        print(f"  Status: {resp.status_code}")
        print(f"  {resp.text}")
        print("  (This may fail if the event has no start/end dates set)")

    # ---------------------------------------------------------------
    # Step 4: Check bulk eligibility for the event
    # ---------------------------------------------------------------
    print_step(4, f"Checking bulk eligibility for event {event_id}")
    resp = session.get(
        f"{base}/api/admin/cpe/eligibility/{event_id}",
        headers=headers,
    )
    if resp.status_code == 200:
        data = resp.json()
        print(f"  Total participants: {data.get('total_participants')}")
        print(f"  Eligible: {data.get('eligible_count')}")
        print(f"  Ineligible: {data.get('ineligible_count')}")
        if data.get("participants"):
            for p in data["participants"][:5]:
                print(f"    - {p.get('first_name')} {p.get('last_name')}: "
                      f"eligible={p.get('eligible')} "
                      f"(nc={p['criteria']['has_nextcloud_login']}, "
                      f"pdns={p['criteria']['has_powerdns_login']}, "
                      f"vpn={p['criteria']['has_vpn_assigned']})")
            if len(data["participants"]) > 5:
                print(f"    ... and {len(data['participants']) - 5} more")
    else:
        print(f"  Status: {resp.status_code} - {resp.text}")

    # ---------------------------------------------------------------
    # Step 5: Issue a certificate (skip eligibility for testing)
    # ---------------------------------------------------------------
    print_step(5, f"Issuing certificate for user {user_id} (skip_eligibility=true)")
    resp = session.post(
        f"{base}/api/admin/cpe/issue",
        json={
            "user_id": user_id,
            "event_id": event_id,
            "skip_eligibility": True,
        },
        headers=headers,
    )
    cert_id = None
    cert_number = None
    if resp.status_code == 200:
        data = resp.json()
        cert_id = data.get("certificate_id")
        cert_number = data.get("certificate_number")
        print(f"  Certificate issued!")
        print(f"  ID: {cert_id}")
        print(f"  Number: {cert_number}")
        print(f"  PDF generated: {data.get('pdf_generated')}")
    else:
        print(f"  Status: {resp.status_code}")
        print(f"  {resp.text}")
        detail = resp.json().get("detail", "")
        if "already exists" in detail:
            print("  (Certificate already exists for this user+event)")
        elif "not found" in detail:
            print("  (Check that the event_id and user_id are correct)")

    # ---------------------------------------------------------------
    # Step 6: List certificates for the event
    # ---------------------------------------------------------------
    print_step(6, f"Listing certificates for event {event_id}")
    resp = session.get(
        f"{base}/api/admin/cpe/certificates/{event_id}",
        headers=headers,
    )
    if resp.status_code == 200:
        data = resp.json()
        print(f"  Total certificates: {data.get('total')}")
        for cert in data.get("certificates", []):
            print(f"    - {cert['certificate_number']}: "
                  f"{cert.get('first_name')} {cert.get('last_name')} "
                  f"({cert.get('email')}) "
                  f"status={cert['status']} "
                  f"pdf={'yes' if cert.get('pdf_generated') else 'NO'}")
            # Grab cert_id if we didn't issue one above
            if not cert_id and cert.get("user_id") == user_id:
                cert_id = cert["id"]
                cert_number = cert["certificate_number"]
    else:
        print(f"  Status: {resp.status_code} - {resp.text}")

    # ---------------------------------------------------------------
    # Step 7: Start Gotenberg (if Render API configured)
    # ---------------------------------------------------------------
    gotenberg_started = False
    if render_enabled:
        print_step(7, "Starting Gotenberg via Render API")
        # Derive the internal Gotenberg URL from the base URL's service
        gotenberg_url = "http://cyberx-gotenberg:3000"
        gotenberg_started = start_gotenberg(
            args.render_api_key, args.gotenberg_service_id, gotenberg_url
        )
        if not gotenberg_started:
            print("  WARNING: Gotenberg may not be ready. PDF tests may fail.")
            # We can't directly reach Gotenberg from outside Render's network,
            # so we'll just proceed and let the API tests tell us if it works.
            print("  (Note: Can't verify from outside Render - will test via API)")
            gotenberg_started = True  # Proceed anyway
    else:
        print_step(7, "Skipping Gotenberg startup (no Render API credentials)")

    try:
        # ---------------------------------------------------------------
        # Step 8: Test bulk regenerate PDFs
        # ---------------------------------------------------------------
        if cert_id:
            print_step(8, f"Bulk regenerate PDFs for event {event_id}")
            resp = session.post(
                f"{base}/api/admin/cpe/certificates/regenerate/bulk",
                json={"event_id": event_id},
                headers=headers,
                timeout=300,  # May take a while for bulk operations
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"  Regenerated: {data.get('regenerated_count')}")
                print(f"  Failed: {data.get('failed_count')}")
                print(f"  Skipped (revoked): {data.get('skipped_revoked_count')}")
                if data.get("regenerated"):
                    for r in data["regenerated"]:
                        print(f"    - {r.get('certificate_number')}: OK")
                if data.get("failed"):
                    for f in data["failed"]:
                        print(f"    - {f.get('certificate_number')}: FAILED - {f.get('error')}")
            else:
                print(f"  Status: {resp.status_code} - {resp.text}")
        else:
            print_step(8, "Skipping bulk regenerate (no certificate available)")

        # ---------------------------------------------------------------
        # Step 9: Test single regenerate PDF
        # ---------------------------------------------------------------
        if cert_id:
            print_step(9, f"Regenerating PDF for certificate {cert_id}")
            resp = session.post(
                f"{base}/api/admin/cpe/certificates/{cert_id}/regenerate",
                headers=headers,
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"  Regenerated: {data.get('certificate_number')}")
                print(f"  PDF generated at: {data.get('pdf_generated_at')}")
            else:
                print(f"  Status: {resp.status_code} - {resp.text}")
        else:
            print_step(9, "Skipping regenerate test (no certificate available)")

        # ---------------------------------------------------------------
        # Step 10: Test participant download endpoint
        # ---------------------------------------------------------------
        if cert_id:
            print_step(10, f"Testing participant certificate download (cert {cert_id})")

            resp = session.get(f"{base}/api/cpe/my-certificates", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                certs_list = data.get("certificates", [])
                print(f"  My certificates (as logged-in admin): {len(certs_list)}")
                for c in certs_list:
                    print(f"    - {c.get('certificate_number')}: {c.get('cpe_hours')} CPE hours")
                if user_id != admin_user_id and not certs_list:
                    print("  (Expected: cert was issued for a different user)")
            else:
                print(f"  List status: {resp.status_code} - {resp.text}")

            # Download test - only works if cert belongs to the logged-in user
            if user_id == admin_user_id:
                resp = session.get(
                    f"{base}/api/cpe/my-certificates/{cert_id}/download",
                    headers=headers,
                    allow_redirects=False,
                )
                if resp.status_code == 302:
                    location = resp.headers.get("Location", "")
                    print(f"  Download redirect: 302")
                    print(f"  Location: {location[:100]}...")
                elif resp.status_code == 200:
                    content_type = resp.headers.get("Content-Type", "")
                    print(f"  Download: 200 ({content_type}, {len(resp.content)} bytes)")
                else:
                    print(f"  Download status: {resp.status_code}")
                    print(f"  {resp.text[:200]}")
            else:
                print(f"  Skipping download test (cert belongs to user {user_id}, "
                      f"logged in as user {admin_user_id})")
        else:
            print_step(10, "Skipping download test (no certificate available)")

        # ---------------------------------------------------------------
        # Step 11: Test revoke
        # ---------------------------------------------------------------
        if cert_id:
            print_step(11, f"Revoking certificate {cert_id}")
            resp = session.post(
                f"{base}/api/admin/cpe/certificates/{cert_id}/revoke",
                json={"reason": "Test revocation from test script"},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"  Revoked: {data.get('certificate_number')}")
                print(f"  Revoked at: {data.get('revoked_at')}")
            else:
                print(f"  Status: {resp.status_code} - {resp.text}")

            # Verify download is blocked after revocation
            print("\n  Verifying download is blocked after revocation...")
            resp = session.get(
                f"{base}/api/cpe/my-certificates/{cert_id}/download",
                headers=headers,
                allow_redirects=False,
            )
            if resp.status_code in (400, 403, 404, 410):
                print(f"  Download blocked as expected: {resp.status_code}")
            else:
                print(f"  Unexpected status: {resp.status_code} - {resp.text[:200]}")
        else:
            print_step(11, "Skipping revoke test (no certificate available)")

    finally:
        # ---------------------------------------------------------------
        # Cleanup: Suspend Gotenberg
        # ---------------------------------------------------------------
        if render_enabled:
            print(f"\n{'='*60}")
            print("  Cleanup: Suspending Gotenberg")
            print(f"{'='*60}")
            stop_gotenberg(args.render_api_key, args.gotenberg_service_id)

    # ---------------------------------------------------------------
    # Done
    # ---------------------------------------------------------------
    print(f"\n{'='*60}")
    print("  Test complete!")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
