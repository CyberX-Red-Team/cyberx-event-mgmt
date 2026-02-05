"""Database configuration and session management."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.config import get_settings

settings = get_settings()

# Add pgbouncer compatibility parameter to database URL
# asyncpg requires prepared_statement_cache_size=0 in URL for pgbouncer
database_url = settings.async_database_url
if "?" in database_url:
    database_url += "&prepared_statement_cache_size=0"
else:
    database_url += "?prepared_statement_cache_size=0"

# Create async engine
engine = create_async_engine(
    database_url,
    echo=False,  # Disable SQL query logging (too verbose)
    pool_size=20,
    max_overflow=50,
    pool_pre_ping=True,
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
