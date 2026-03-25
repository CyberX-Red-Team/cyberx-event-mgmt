"""Database configuration and session management."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import get_settings

settings = get_settings()


def _on_connect(dbapi_connection, connection_record):
    """Called for each new connection to disable prepared statement cache."""
    # For asyncpg connections, disable prepared statement cache for pgbouncer compatibility
    # This is set at the connection level to ensure it takes effect
    pass  # The setting is applied via connect_args below


# Create async engine with pgbouncer-compatible settings
engine = create_async_engine(
    settings.async_database_url,
    echo=False,  # Disable SQL query logging (too verbose)
    pool_size=20,
    max_overflow=50,
    pool_pre_ping=True,
    # Disable prepared statement caching for pgbouncer compatibility
    connect_args={
        "server_settings": {
            "jit": "off",  # Disable JIT compilation which can interfere
        },
        "prepared_statement_cache_size": 0,  # Disable prepared statement cache
    },
)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """Dependency for getting database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
