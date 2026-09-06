from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings
from app.core.logging import logger

Base = declarative_base()

# SQLAlchemy Async Engine configuration
engine = None
AsyncSessionLocal = None

try:
    db_url = settings.DATABASE_URL
    # Normalize Postgres dialect for async engine (Supabase and Render provide postgres:// or postgresql://)
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
    )
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
except Exception as e:
    logger.warning(f"Could not initialize async SQLAlchemy engine with URL: {e}. In-memory repos active.")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding database sessions."""
    if AsyncSessionLocal is None:
        yield None  # Repositories fall back to domain memory store
        return

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
