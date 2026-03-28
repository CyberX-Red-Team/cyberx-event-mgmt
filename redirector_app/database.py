"""Async SQLAlchemy engine and session factory for the standalone app.

Requires PostgreSQL via asyncpg. Set DATABASE_URL in redirector_app/.env.

Usage:
    DATABASE_URL=postgresql+asyncpg://cyberx:changeme@localhost:5432/cyberx_events
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://cyberx:changeme@localhost:5432/cyberx_events"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncSession:
    """FastAPI dependency: yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables() -> None:
    """Create all tables (idempotent). Called at application startup."""
    # Import models so their metadata is registered with Base
    from redirector_app import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
