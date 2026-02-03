"""Test authentication endpoints."""
import asyncio
import httpx


API_BASE = "http://localhost:8000"


async def test_authentication():
    """Test the authentication flow."""
    print("\n🧪 Testing Authentication Flow")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        # Test 1: Login
        print("\n1️⃣  Testing login...")
        login_response = await client.post(
            f"{API_BASE}/api/auth/login",
            json={
                "username": "admin@cyberxredteam.org",
                "password": "admin123"
            }
        )

        if login_response.status_code == 200:
            print("   ✅ Login successful!")
            login_data = login_response.json()
            print(f"   User: {login_data['user']['email']}")
            print(f"   Is Admin: {login_data['user']['is_admin']}")
            print(f"   Expires: {login_data['expires_at']}")

            # Extract session cookie
            session_cookie = login_response.cookies.get("session_token")
            if session_cookie:
                print(f"   Session token received: {session_cookie[:20]}...")
            else:
                print("   ⚠️  No session cookie received")
                return
        else:
            print(f"   ❌ Login failed: {login_response.status_code}")
            print(f"   Response: {login_response.text}")
            return

        # Test 2: Get current user (/me)
        print("\n2️⃣  Testing /me endpoint...")
        me_response = await client.get(
            f"{API_BASE}/api/auth/me",
            cookies={"session_token": session_cookie}
        )

        if me_response.status_code == 200:
            print("   ✅ /me endpoint successful!")
            me_data = me_response.json()
            print(f"   User: {me_data['user']['first_name']} {me_data['user']['last_name']}")
            print(f"   Email: {me_data['user']['email']}")
            print(f"   Is Admin: {me_data['is_admin']}")
        else:
            print(f"   ❌ /me failed: {me_response.status_code}")
            print(f"   Response: {me_response.text}")

        # Test 3: Unauthenticated request
        print("\n3️⃣  Testing unauthenticated request...")
        unauth_response = await client.get(f"{API_BASE}/api/auth/me")

        if unauth_response.status_code == 401:
            print("   ✅ Properly rejected unauthenticated request!")
        else:
            print(f"   ⚠️  Unexpected status: {unauth_response.status_code}")

        # Test 4: Logout
        print("\n4️⃣  Testing logout...")
        logout_response = await client.post(
            f"{API_BASE}/api/auth/logout",
            cookies={"session_token": session_cookie}
        )

        if logout_response.status_code == 200:
            print("   ✅ Logout successful!")
        else:
            print(f"   ❌ Logout failed: {logout_response.status_code}")

        # Test 5: Use session after logout
        print("\n5️⃣  Testing session after logout...")
        after_logout_response = await client.get(
            f"{API_BASE}/api/auth/me",
            cookies={"session_token": session_cookie}
        )

        if after_logout_response.status_code == 401:
            print("   ✅ Session properly invalidated after logout!")
        else:
            print(f"   ⚠️  Unexpected status: {after_logout_response.status_code}")

    print("\n" + "=" * 60)
    print("✅ Authentication tests complete!\n")


async def main():
    """Main function."""
    try:
        await test_authentication()
    except httpx.ConnectError:
        print("\n❌ Could not connect to API server at http://localhost:8000")
        print("\nPlease start the server first:")
        print("   cd backend")
        print("   uvicorn app.main:app --reload")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
