"""Quick database connection test."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.database import AsyncSessionLocal, engine
from app.config import get_settings


async def test_connection():
    """Test database connection."""
    print("🔍 Testing database connection...")

    settings = get_settings()
    print(f"   Database URL: {settings.DATABASE_URL}")

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            print("✅ Database connection successful!")
            return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("\nTroubleshooting:")
        print("  1. Is PostgreSQL running? Run: docker compose ps")
        print("  2. Start PostgreSQL: docker compose up -d postgres")
        print("  3. Check logs: docker compose logs postgres")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)
