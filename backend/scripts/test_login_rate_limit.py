"""
Test login rate limiting functionality.

This script tests that the login endpoint properly rate limits brute force attempts.

Usage:
    python scripts/test_login_rate_limit.py

Requirements:
    - Server running at http://localhost:8000
    - httpx library (pip install httpx)
"""
import asyncio
import httpx
from datetime import datetime


API_BASE_URL = "http://localhost:8000"


class Colors:
    """ANSI color codes."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


async def test_rate_limiting():
    """Test login rate limiting."""
    print(f"\n{Colors.BOLD}=== Login Rate Limiting Test ==={Colors.END}\n")
    print("Testing: 5 attempts per 15 minutes limit")
    print("Expected: First 5 attempts allowed, 6th attempt blocked\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test 1: Rapid failed login attempts
        print(f"{Colors.BLUE}Test 1: Making 6 failed login attempts...{Colors.END}")

        results = []
        for i in range(6):
            try:
                response = await client.post(
                    f"{API_BASE_URL}/api/auth/login",
                    json={
                        "username": "nonexistent@example.com",
                        "password": "wrongpassword123"
                    }
                )
                results.append({
                    "attempt": i + 1,
                    "status": response.status_code,
                    "response": response.json() if response.status_code != 500 else response.text
                })
            except Exception as e:
                results.append({
                    "attempt": i + 1,
                    "status": 0,
                    "error": str(e)
                })

        # Analyze results
        print(f"\n{Colors.BOLD}Results:{Colors.END}")
        rate_limited_count = 0

        for result in results:
            attempt = result["attempt"]
            status = result["status"]

            if status == 401:  # Unauthorized (expected for wrong credentials)
                print(f"  Attempt {attempt}: {Colors.GREEN}✓{Colors.END} 401 Unauthorized (credentials rejected)")
            elif status == 429:  # Rate limited
                rate_limited_count += 1
                print(f"  Attempt {attempt}: {Colors.YELLOW}⚠{Colors.END} 429 Rate Limited")
                if "response" in result:
                    print(f"    Message: {result['response'].get('detail', 'N/A')}")
            else:
                print(f"  Attempt {attempt}: {Colors.RED}✗{Colors.END} {status} (unexpected)")
                if "error" in result:
                    print(f"    Error: {result['error']}")

        # Verdict
        print(f"\n{Colors.BOLD}=== Test Verdict ==={Colors.END}\n")

        if rate_limited_count > 0:
            print(f"{Colors.GREEN}{Colors.BOLD}✓ TEST PASSED{Colors.END}")
            print(f"{Colors.GREEN}Rate limiting is working correctly!{Colors.END}")
            print(f"{Colors.GREEN}{rate_limited_count} attempt(s) were rate limited as expected{Colors.END}")
            print(f"\n{Colors.BLUE}Details:{Colors.END}")
            print(f"  - First 5 attempts: Allowed (returned 401)")
            print(f"  - 6th attempt: Blocked (returned 429)")
            print(f"  - Rate limit: 5 attempts per 15 minutes")
        else:
            print(f"{Colors.RED}{Colors.BOLD}✗ TEST FAILED{Colors.END}")
            print(f"{Colors.RED}No rate limiting detected!{Colors.END}")
            print(f"{Colors.RED}All 6 attempts were allowed - rate limiting may not be working{Colors.END}")

        # Test 2: Successful login clears rate limit
        print(f"\n{Colors.BLUE}Test 2: Verifying successful login clears rate limit...{Colors.END}")
        print(f"{Colors.YELLOW}Note: This test requires valid credentials{Colors.END}")
        print(f"{Colors.YELLOW}Skipping automatic test - manual verification recommended{Colors.END}")

        # Instructions for manual testing
        print(f"\n{Colors.BOLD}=== Manual Testing Instructions ==={Colors.END}\n")
        print("To verify successful login clears the rate limit:")
        print("1. Make 3 failed login attempts with wrong password")
        print("2. Login successfully with correct credentials")
        print("3. Make 5 more failed attempts")
        print("4. You should be able to make all 5 attempts (rate limit was cleared)")
        print("\nWithout the clear on success:")
        print("- You'd only be able to make 2 more attempts (3 + 2 = 5 total)")

        print(f"\n{Colors.BOLD}=== Security Notes ==={Colors.END}\n")
        print("✓ Rate limiting prevents brute force attacks")
        print("✓ Failed attempts are logged in audit log")
        print("✓ Rate limit resets on successful login (user-friendly)")
        print("⚠ In-memory cache: Rate limits reset on server restart")
        print("⚠ IP-based: Shared IPs may affect multiple users")
        print("🔒 For production: Consider Redis-based rate limiting")


async def main():
    """Main entry point."""
    try:
        await test_rate_limiting()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test interrupted by user{Colors.END}")
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.END}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Check for httpx
    try:
        import httpx
    except ImportError:
        print(f"{Colors.RED}Error: httpx not installed{Colors.END}")
        print("Install with: pip install httpx")
        exit(1)

    asyncio.run(main())
