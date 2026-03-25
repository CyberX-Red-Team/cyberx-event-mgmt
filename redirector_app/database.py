"""Async SQLAlchemy engine and session factory for the standalone app.

Defaults to SQLite via aiosqlite. Override with DATABASE_URL env var for PostgreSQL.

Usage:
    DATABASE_URL=sqlite+aiosqlite:///./redirectors.db     (default)
    DATABASE_URL=postgresql+asyncpg://user:pass@host/db   (production)
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "sqlite+aiosqlite:///./redirectors.db"
)

# SQLite needs check_same_thread=False; asyncpg needs no special args
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args=connect_args,
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
