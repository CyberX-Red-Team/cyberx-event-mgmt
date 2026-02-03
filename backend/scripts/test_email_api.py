"""Test email API endpoints."""
import asyncio
import httpx


API_BASE = "http://localhost:8000"


async def test_email_api():
    """Test the email API endpoints."""
    print("\n🧪 Testing Email API Endpoints")
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
            return

        print("   ✅ Login successful!")
        session_cookie = login_response.cookies.get("session_token")
        cookies = {"session_token": session_cookie}

        # Step 2: List email templates
        print("\n2️⃣  Testing list templates...")
        templates_response = await client.get(
            f"{API_BASE}/api/email/templates",
            cookies=cookies
        )

        if templates_response.status_code == 200:
            print("   ✅ List templates working!")
            data = templates_response.json()
            for t in data["templates"]:
                print(f"      - {t['name']}: {t['description']}")
        else:
            print(f"   ❌ Templates failed: {templates_response.status_code}")
            print(f"   Response: {templates_response.text}")

        # Step 3: Get email stats
        print("\n3️⃣  Testing email stats...")
        stats_response = await client.get(
            f"{API_BASE}/api/email/stats",
            cookies=cookies
        )

        if stats_response.status_code == 200:
            print("   ✅ Email stats working!")
            data = stats_response.json()
            print(f"      Total sent: {data['total_sent']}")
            print(f"      Delivered: {data['delivered']}")
            print(f"      Opened: {data['opened']}")
            print(f"      Bounced: {data['bounced']}")
        else:
            print(f"   ❌ Stats failed: {stats_response.status_code}")
            print(f"   Response: {stats_response.text}")

        # Step 4: Test webhook health
        print("\n4️⃣  Testing webhook health...")
        webhook_response = await client.get(f"{API_BASE}/api/webhooks/health")

        if webhook_response.status_code == 200:
            print("   ✅ Webhook health working!")
            data = webhook_response.json()
            print(f"      Status: {data['status']}")
            print(f"      Webhooks: {', '.join(data['webhooks'])}")
        else:
            print(f"   ❌ Webhook health failed: {webhook_response.status_code}")

        # Step 5: Test send email (dry run - will fail without valid SendGrid key)
        print("\n5️⃣  Testing send email endpoint (expects failure without valid API key)...")
        send_response = await client.post(
            f"{API_BASE}/api/email/send",
            cookies=cookies,
            json={
                "participant_id": 1,
                "template_name": "password"
            }
        )

        if send_response.status_code == 200:
            data = send_response.json()
            if data["success"]:
                print("   ✅ Email sent successfully!")
            else:
                print(f"   ⚠️  Expected failure: {data['message']}")
        elif send_response.status_code == 404:
            print("   ⚠️  Participant not found (expected if ID 1 doesn't exist)")
        else:
            print(f"   ⚠️  Send response: {send_response.status_code}")
            # This is expected to fail without a valid SendGrid API key

        # Step 6: Test SendGrid webhook simulation
        print("\n6️⃣  Testing SendGrid webhook handler...")
        webhook_event = [{
            "email": "test@example.com",
            "event": "delivered",
            "sg_message_id": "test-message-id",
            "timestamp": 1609459200
        }]

        webhook_response = await client.post(
            f"{API_BASE}/api/webhooks/sendgrid",
            json=webhook_event
        )

        if webhook_response.status_code == 200:
            print("   ✅ SendGrid webhook working!")
            data = webhook_response.json()
            print(f"      Status: {data['status']}")
            print(f"      Processed: {data['processed']}/{data['total']}")
        else:
            print(f"   ❌ Webhook failed: {webhook_response.status_code}")
            print(f"   Response: {webhook_response.text}")

    print("\n" + "=" * 60)
    print("✅ Email API tests complete!")
    print("\nNote: Actual email sending requires a valid SendGrid API key")
    print("      Configure SENDGRID_API_KEY in .env for production use\n")


async def main():
    """Main function."""
    try:
        await test_email_api()
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
