"""Create an admin user for testing."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.utils.security import hash_password


async def create_admin_user(
    email: str = "admin@cyberxredteam.org",
    password: str = "admin123",
    first_name: str = "Admin",
    last_name: str = "User"
):
    """
    Create an admin user.

    Args:
        email: Admin email
        password: Admin password
        first_name: First name
        last_name: Last name
    """
    print(f"\n🔐 Creating admin user: {email}")

    async with AsyncSessionLocal() as session:
        # Check if user already exists
        result = await session.execute(
            select(User).where(User.email == email)
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            print(f"⚠️  User {email} already exists. Updating password...")
            existing_user.password_hash = hash_password(password)
            existing_user.is_admin = True
            existing_user.is_active = True
            existing_user.confirmed = 'YES'
            await session.commit()
            print(f"✅ Updated user: {email}")
            print(f"   Password: {password}")
            return

        # Create new admin user
        admin = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            country="USA",
            confirmed="YES",
            email_status="GOOD",
            is_admin=True,
            is_active=True,
            password_hash=hash_password(password),
            pandas_username=f"admin_{email.split('@')[0]}"
        )

        session.add(admin)
        await session.commit()

        print(f"✅ Created admin user successfully!")
        print(f"   Email: {email}")
        print(f"   Password: {password}")
        print(f"   Is Admin: True")


async def main():
    """Main function."""
    print("🚀 CyberX Event Management - Admin User Creator")
    print("=" * 60)

    # Get credentials from command line or use defaults
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        email = input("Admin email (default: admin@cyberxredteam.org): ").strip()
        if not email:
            email = "admin@cyberxredteam.org"

    if len(sys.argv) > 2:
        password = sys.argv[2]
    else:
        password = input("Admin password (default: admin123): ").strip()
        if not password:
            password = "admin123"

    try:
        await create_admin_user(email=email, password=password)
        print("\n" + "=" * 60)
        print("✅ Setup complete!")
        print(f"\nYou can now login with:")
        print(f"   Email: {email}")
        print(f"   Password: {password}")

    except Exception as e:
        print(f"\n❌ Error creating admin user: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
