"""
Check password states for sponsors in the database.

This diagnostic script helps identify sponsors who may be missing passwords
or have password-related issues that could cause login failures.

Usage:
    python -m scripts.check_sponsor_passwords
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import AsyncSessionLocal
from app.models.user import User
from sqlalchemy import select


async def check_sponsor_passwords():
    """Check password state for all sponsors."""
    print("=" * 80)
    print("Sponsor Password State Diagnostic")
    print("=" * 80)
    print()

    async with AsyncSessionLocal() as session:
        # Get all sponsors
        result = await session.execute(
            select(User)
            .where(User.role == 'sponsor')
            .order_by(User.created_at.desc())
        )
        sponsors = list(result.scalars().all())

        if not sponsors:
            print("❌ No sponsors found in database")
            return

        print(f"Found {len(sponsors)} sponsor(s)\n")

        # Track statistics
        has_password = 0
        missing_password = 0
        has_username = 0
        missing_username = 0
        confirmed_sponsors = 0

        # Check each sponsor
        for sponsor in sponsors:
            # Check password state
            has_encrypted = sponsor._pandas_password_encrypted is not None
            password_value = sponsor.pandas_password  # This uses the property getter
            password_decrypts = password_value is not None

            # Determine status
            if has_encrypted and password_decrypts:
                password_status = "✅ Has password (encrypted)"
                has_password += 1
            elif has_encrypted and not password_decrypts:
                password_status = "⚠️  Encrypted field set but decrypts to None (ISSUE!)"
                missing_password += 1
            else:
                password_status = "❌ No password"
                missing_password += 1

            # Check username
            if sponsor.pandas_username:
                username_status = f"✅ {sponsor.pandas_username}"
                has_username += 1
            else:
                username_status = "❌ No username"
                missing_username += 1

            # Check confirmation
            if sponsor.confirmed == 'YES':
                confirmed_sponsors += 1

            print(f"Sponsor: {sponsor.email} (ID: {sponsor.id})")
            print(f"  Created: {sponsor.created_at}")
            print(f"  Confirmed: {sponsor.confirmed}")
            print(f"  Username: {username_status}")
            print(f"  Password: {password_status}")
            print(f"  Password Hash: {'✅ Set' if sponsor.password_hash else '❌ Missing'}")
            print(f"  Active: {'✅ Yes' if sponsor.is_active else '❌ No'}")

            # Show problematic state
            if sponsor.confirmed == 'YES' and not has_encrypted:
                print(f"  ⚠️  WARNING: Confirmed but no password!")

            if sponsor.pandas_username and not has_encrypted:
                print(f"  ⚠️  WARNING: Has username but no password!")

            print()

        # Summary
        print("=" * 80)
        print("Summary:")
        print(f"  Total sponsors: {len(sponsors)}")
        print(f"  Confirmed: {confirmed_sponsors}")
        print(f"  With username: {has_username}")
        print(f"  Without username: {missing_username}")
        print(f"  With password: {has_password}")
        print(f"  Without password: {missing_password}")
        print("=" * 80)

        # Recommendations
        if missing_password > 0:
            print()
            print("⚠️  RECOMMENDATIONS:")
            print()
            print(f"  Found {missing_password} sponsor(s) without passwords.")
            print()
            print("  Possible causes:")
            print("  1. Sponsor was created before credential generation logic was added")
            print("  2. Sponsor role was changed after creation (was invitee, became sponsor)")
            print("  3. Password field was cleared/corrupted")
            print()
            print("  Solutions:")
            print("  1. Use admin UI to manually set a password for affected sponsors")
            print("  2. Use reset workflow to re-invite the sponsor")
            print("  3. Check logs during next sponsor confirmation to see why password is regenerated")
            print()


async def main():
    """Run the diagnostic check."""
    try:
        await check_sponsor_passwords()
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error during diagnostic: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
