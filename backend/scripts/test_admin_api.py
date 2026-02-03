"""Test admin API endpoints."""
import asyncio
import httpx


API_BASE = "http://localhost:8000"


async def test_admin_api():
    """Test the admin API endpoints."""
    print("\n🧪 Testing Admin API Endpoints")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        # Step 1: Login as admin
        print("\n1️⃣  Logging in as admin...")
        login_response = await client.post(
            f"{API_BASE}/api/auth/login",
            json={
                "username": "admin@cyberxredteam.org",
                "password": "admin123"
            }
        )

        if login_response.status_code != 200:
            print(f"   ❌ Login failed: {login_response.status_code}")
            print(f"   Response: {login_response.text}")
            return

        print("   ✅ Login successful!")
        session_cookie = login_response.cookies.get("session_token")
        cookies = {"session_token": session_cookie}

        # Step 2: Get dashboard stats
        print("\n2️⃣  Testing dashboard endpoint...")
        dashboard_response = await client.get(
            f"{API_BASE}/api/admin/dashboard",
            cookies=cookies
        )

        if dashboard_response.status_code == 200:
            print("   ✅ Dashboard endpoint working!")
            data = dashboard_response.json()
            print(f"   Invitees: {data['stats']['participants']['total_invitees']}")
            print(f"   Confirmed: {data['stats']['participants']['confirmed_count']}")
            print(f"   VPN Total: {data['stats']['vpn']['total_credentials']}")
            print(f"   VPN Available: {data['stats']['vpn']['available_count']}")
        else:
            print(f"   ❌ Dashboard failed: {dashboard_response.status_code}")
            print(f"   Response: {dashboard_response.text}")

        # Step 3: List participants
        print("\n3️⃣  Testing list participants...")
        list_response = await client.get(
            f"{API_BASE}/api/admin/participants?page=1&page_size=5",
            cookies=cookies
        )

        if list_response.status_code == 200:
            print("   ✅ List participants working!")
            data = list_response.json()
            print(f"   Total: {data['total']}")
            print(f"   Page: {data['page']} of {data['total_pages']}")
            if data['items']:
                print(f"   First participant: {data['items'][0]['first_name']} {data['items'][0]['last_name']}")
        else:
            print(f"   ❌ List failed: {list_response.status_code}")
            print(f"   Response: {list_response.text}")

        # Step 4: Get participant stats
        print("\n4️⃣  Testing participant stats...")
        stats_response = await client.get(
            f"{API_BASE}/api/admin/participants/stats",
            cookies=cookies
        )

        if stats_response.status_code == 200:
            print("   ✅ Participant stats working!")
            data = stats_response.json()
            print(f"   Total: {data['total_invitees']}")
            print(f"   Confirmed: {data['confirmed_count']}")
            print(f"   With VPN: {data['with_vpn_count']}")
        else:
            print(f"   ❌ Stats failed: {stats_response.status_code}")
            print(f"   Response: {stats_response.text}")

        # Step 5: Get VPN stats
        print("\n5️⃣  Testing VPN stats...")
        vpn_stats_response = await client.get(
            f"{API_BASE}/api/vpn/stats",
            cookies=cookies
        )

        if vpn_stats_response.status_code == 200:
            print("   ✅ VPN stats working!")
            data = vpn_stats_response.json()
            print(f"   Total credentials: {data['total_credentials']}")
            print(f"   Available: {data['available_count']}")
            print(f"   Cyber: {data['cyber_available']}/{data['cyber_total']}")
            print(f"   Kinetic: {data['kinetic_available']}/{data['kinetic_total']}")
        else:
            print(f"   ❌ VPN stats failed: {vpn_stats_response.status_code}")
            print(f"   Response: {vpn_stats_response.text}")

        # Step 6: List VPN credentials
        print("\n6️⃣  Testing list VPN credentials...")
        vpn_list_response = await client.get(
            f"{API_BASE}/api/vpn/credentials?page=1&page_size=5",
            cookies=cookies
        )

        if vpn_list_response.status_code == 200:
            print("   ✅ List VPN credentials working!")
            data = vpn_list_response.json()
            print(f"   Total: {data['total']}")
            if data['items']:
                vpn = data['items'][0]
                print(f"   First VPN: ID={vpn['id']}, Type={vpn['key_type']}, Available={vpn['is_available']}")
        else:
            print(f"   ❌ VPN list failed: {vpn_list_response.status_code}")
            print(f"   Response: {vpn_list_response.text}")

        # Step 7: Create a test participant
        print("\n7️⃣  Testing create participant...")
        create_response = await client.post(
            f"{API_BASE}/api/admin/participants",
            cookies=cookies,
            json={
                "email": "test.user@example.com",
                "first_name": "Test",
                "last_name": "User",
                "country": "USA",
                "confirmed": "UNKNOWN"
            }
        )

        test_participant_id = None
        if create_response.status_code == 201:
            print("   ✅ Create participant working!")
            data = create_response.json()
            test_participant_id = data['id']
            print(f"   Created: ID={data['id']}, {data['first_name']} {data['last_name']}")
            print(f"   Pandas username: {data['pandas_username']}")
        elif create_response.status_code == 400 and "already exists" in create_response.text:
            print("   ⚠️  Test participant already exists (this is fine)")
            # Get the existing participant
            search_response = await client.get(
                f"{API_BASE}/api/admin/participants?search=test.user@example.com",
                cookies=cookies
            )
            if search_response.status_code == 200:
                items = search_response.json()['items']
                if items:
                    test_participant_id = items[0]['id']
        else:
            print(f"   ❌ Create failed: {create_response.status_code}")
            print(f"   Response: {create_response.text}")

        # Step 8: Assign VPN to test participant
        if test_participant_id:
            print("\n8️⃣  Testing VPN assignment...")
            assign_response = await client.post(
                f"{API_BASE}/api/vpn/assign",
                cookies=cookies,
                json={
                    "participant_id": test_participant_id,
                    "key_type": "cyber"
                }
            )

            if assign_response.status_code == 200:
                data = assign_response.json()
                if data['success']:
                    print("   ✅ VPN assigned successfully!")
                    print(f"   VPN ID: {data['vpn_id']}")
                else:
                    print(f"   ⚠️  {data['message']}")
            else:
                print(f"   ❌ Assign failed: {assign_response.status_code}")
                print(f"   Response: {assign_response.text}")

            # Step 9: Get VPN config for participant
            print("\n9️⃣  Testing VPN config download...")
            config_response = await client.get(
                f"{API_BASE}/api/vpn/participant/{test_participant_id}/config",
                cookies=cookies
            )

            if config_response.status_code == 200:
                print("   ✅ VPN config retrieved!")
                data = config_response.json()
                print(f"   Filename: {data['filename']}")
                print(f"   Config preview: {data['config'][:100]}...")
            elif config_response.status_code == 404:
                print("   ⚠️  No VPN assigned (expected if already had one)")
            else:
                print(f"   ❌ Config failed: {config_response.status_code}")
                print(f"   Response: {config_response.text}")

            # Step 10: Delete test participant
            print("\n🔟  Cleaning up test participant...")
            delete_response = await client.delete(
                f"{API_BASE}/api/admin/participants/{test_participant_id}",
                cookies=cookies
            )

            if delete_response.status_code == 200:
                print("   ✅ Test participant deleted!")
            else:
                print(f"   ⚠️  Delete response: {delete_response.status_code}")

    print("\n" + "=" * 60)
    print("✅ Admin API tests complete!\n")


async def main():
    """Main function."""
    try:
        await test_admin_api()
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
