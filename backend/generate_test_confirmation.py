#!/usr/bin/env python3
"""Generate a test confirmation link for testing the confirmation page."""
import asyncio
import secrets
import sys
from datetime import datetime, timezone
from sqlalchemy import select, update
from app.database import engine
from app.models.user import User

async def generate_test_link(email: str = None):
    """Generate a test confirmation link for a specific user.

    Args:
        email: Email address of the user. If not provided, uses the first invitee.
    """
    async with engine.begin() as conn:
        # Get user by email or first invitee
        if email:
            result = await conn.execute(
                select(User).where(User.email == email)
            )
            user = result.first()

            if not user:
                print(f"❌ No user found with email: {email}")
                print("\nAvailable invitees:")
                # Show some available users
                available = await conn.execute(
                    select(User.email, User.first_name, User.last_name, User.role)
                    .where(User.role.in_(['invitee', 'sponsor']))
                    .limit(10)
                )
                for u in available:
                    print(f"  - {u[0]} ({u[1]} {u[2]}) - {u[3]}")
                return
        else:
            result = await conn.execute(
                select(User).where(User.role == 'invitee').limit(1)
            )
            user = result.first()

            if not user:
                print("❌ No invitee users found in database")
                print("\nPlease create a user first, or specify an email address.")
                return

        user_id = user[0]
        email = user[2]  # Assuming email is the 3rd column
        first_name = user[3]

        # Generate confirmation code
        confirmation_code = secrets.token_urlsafe(32)

        # Update user with confirmation code
        await conn.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                confirmation_code=confirmation_code,
                confirmation_sent_at=datetime.now(timezone.utc),
                confirmed='UNKNOWN'  # Reset confirmation status for testing
            )
        )

        print("✅ Test confirmation link generated!\n")
        print(f"User: {first_name} ({email})")
        print(f"User ID: {user_id}\n")
        print("Confirmation URL:")
        print(f"http://localhost:8000/confirm?code={confirmation_code}\n")
        print("Or for production:")
        print(f"https://portal.cyberxredteam.org/confirm?code={confirmation_code}\n")
        print("⚠️  This will work even if the event is inactive (testing mode)")

if __name__ == "__main__":
    # Parse command line arguments
    email_arg = None
    if len(sys.argv) > 1:
        email_arg = sys.argv[1]

    if not email_arg:
        print("Usage: python generate_test_confirmation.py <email>")
        print("\nOr run without email to use the first invitee user.\n")

    asyncio.run(generate_test_link(email_arg))
