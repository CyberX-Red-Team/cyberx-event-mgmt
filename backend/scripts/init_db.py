"""Database initialization script - creates tables and admin user."""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from app.database import engine, Base, AsyncSessionLocal
from app.models import User
from app.utils.security import hash_password


async def create_tables():
    """Create all database tables."""
    print("📦 Creating database tables...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("✅ Tables created successfully")


async def create_admin_user(email: str, password: str):
    """Create an admin user."""
    print(f"\n👤 Creating admin user: {email}")

    async with AsyncSessionLocal() as session:
        # Check if admin exists
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.email == email)
        )
        existing = result.scalar_one_or_none()

        if existing:
            print("⚠️  Admin user already exists")
            return

        # Create admin user
        admin = User(
            email=email,
            first_name="Admin",
            last_name="User",
            country="US",
            confirmed="YES",
            email_status="GOOD",
            pandas_username="admin",
            password_hash=hash_password(password),
            is_admin=True,
            is_active=True,
        )

        session.add(admin)
        await session.commit()

        print(f"✅ Admin user created")
        print(f"   Email: {email}")
        print(f"   Username: admin")
        print(f"   Password: {password}")


async def main():
    """Main initialization function."""
    print("🚀 CyberX Event Management - Database Initialization")
    print("=" * 60)

    # Get admin credentials
    admin_email = input("\n📧 Admin email (default: admin@cyberxredteam.org): ").strip()
    if not admin_email:
        admin_email = "admin@cyberxredteam.org"

    admin_password = input("🔑 Admin password (default: changeme): ").strip()
    if not admin_password:
        admin_password = "changeme"

    # Confirm
    response = input(f"\n⚠️  Create tables and admin user '{admin_email}'? (yes/no): ")
    if response.lower() not in ('yes', 'y'):
        print("❌ Initialization cancelled")
        return

    try:
        # Create tables
        await create_tables()

        # Create admin user
        await create_admin_user(admin_email, admin_password)

        print("\n" + "=" * 60)
        print("✅ Database initialized successfully!")
        print("\nNext steps:")
        print("  1. Run migrations: alembic upgrade head")
        print("  2. Import CSV data: python scripts/import_csv.py")
        print("  3. Start the app: uvicorn app.main:app --reload")

    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
