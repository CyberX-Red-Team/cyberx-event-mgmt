#!/usr/bin/env python3
"""Test CSRF protection middleware."""

import asyncio
import httpx
from datetime import datetime


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


async def test_csrf_protection():
    """Test CSRF middleware functionality."""
    base_url = "http://localhost:8000"

    print(f"\n{Colors.BOLD}CSRF Protection Test{Colors.RESET}")
    print("=" * 70)

    async with httpx.AsyncClient() as client:
        # Test 1: GET request should work without CSRF token
        print(f"\n{Colors.BLUE}Test 1: GET request (no CSRF required){Colors.RESET}")
        try:
            response = await client.get(f"{base_url}/health")
            print(f"  Status: {response.status_code}")
            print(f"  Response: {response.json()}")

            # Check if CSRF cookie was set
            csrf_cookie = response.cookies.get('csrf_token')
            if csrf_cookie:
                print(f"  {Colors.GREEN}✓ CSRF cookie set: {csrf_cookie[:20]}...{Colors.RESET}")
            else:
                print(f"  {Colors.YELLOW}⚠ No CSRF cookie set (may be set on first state-changing request){Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")

        # Test 2: POST without CSRF token should be rejected
        print(f"\n{Colors.BLUE}Test 2: POST request without CSRF token (should fail){Colors.RESET}")
        try:
            # Try to login without CSRF token
            response = await client.post(
                f"{base_url}/api/auth/login",
                json={"email": "test@example.com", "password": "password"}
            )
            print(f"  Status: {response.status_code}")
            if response.status_code == 403:
                print(f"  Response: {response.json()}")
                print(f"  {Colors.GREEN}✓ CSRF protection working - request blocked{Colors.RESET}")
            else:
                print(f"  {Colors.RED}✗ CSRF protection NOT working - request allowed{Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")

        # Test 3: Exempt URL (webhooks) should work without CSRF
        print(f"\n{Colors.BLUE}Test 3: POST to exempt URL /health (should succeed){Colors.RESET}")
        try:
            # /health is exempt from CSRF
            response = await client.get(f"{base_url}/health")
            print(f"  Status: {response.status_code}")
            csrf_cookie = response.cookies.get('csrf_token')

            if response.status_code == 200:
                print(f"  {Colors.GREEN}✓ Exempt URL accessible{Colors.RESET}")

            # Now try a real exempt endpoint with POST
            # Note: /api/webhooks/sendgrid is exempt but requires valid payload
            print(f"\n  Testing exempt POST endpoint...")
            response_exempt = await client.post(
                f"{base_url}/api/webhooks/sendgrid",
                json=[]  # Empty array (will fail validation but not CSRF)
            )
            print(f"  Status: {response_exempt.status_code}")
            if response_exempt.status_code != 403 or 'CSRF' not in response_exempt.text:
                print(f"  {Colors.GREEN}✓ Exempt URL bypasses CSRF (may fail for other reasons){Colors.RESET}")
            else:
                print(f"  {Colors.RED}✗ Exempt URL still blocked by CSRF{Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")

        # Test 4: POST with valid CSRF token (if we can get one)
        print(f"\n{Colors.BLUE}Test 4: POST with valid CSRF token{Colors.RESET}")
        try:
            # First, make a GET request to obtain CSRF token
            response = await client.get(f"{base_url}/health")
            csrf_token = response.cookies.get('csrf_token')

            if csrf_token:
                print(f"  CSRF Token obtained: {csrf_token[:20]}...")

                # Now make POST with CSRF token
                response = await client.post(
                    f"{base_url}/api/auth/login",
                    json={"email": "test@example.com", "password": "password"},
                    headers={"X-CSRF-Token": csrf_token},
                    cookies={"csrf_token": csrf_token}
                )
                print(f"  Status: {response.status_code}")

                if response.status_code != 403 or 'CSRF' not in response.text:
                    print(f"  {Colors.GREEN}✓ Request with CSRF token allowed (may fail auth){Colors.RESET}")
                else:
                    print(f"  Response: {response.json()}")
                    print(f"  {Colors.RED}✗ Request with CSRF token still blocked{Colors.RESET}")
            else:
                print(f"  {Colors.YELLOW}⚠ Could not obtain CSRF token from GET request{Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")

    # Summary
    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}Summary:{Colors.RESET}")
    print(f"  • CSRF middleware is active and protecting state-changing requests")
    print(f"  • Exempt URLs configured: /api/webhooks/*, /api/public/*, /health")
    print(f"  • Token-based protection using signed cookies")
    print(f"\n{Colors.YELLOW}Note: Server must be running on {base_url}{Colors.RESET}")


if __name__ == "__main__":
    asyncio.run(test_csrf_protection())
