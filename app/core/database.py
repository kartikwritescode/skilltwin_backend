from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core.config import settings
from app.core.logging import logger

# SQLAlchemy Async Engine configuration
engine = None
AsyncSessionLocal = None


def _create_engine(url: str):
    db_url = url
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    connect_args = {}
    if "sqlite" in db_url:
        connect_args["check_same_thread"] = False
    else:
        # Crucial for Supabase transaction pooler / pgbouncer (port 6543)
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        if "localhost" not in db_url and "127.0.0.1" not in db_url:
            connect_args["ssl"] = "require"

    new_engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        connect_args=connect_args,
    )
    new_session_factory = async_sessionmaker(
        bind=new_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    return new_engine, new_session_factory


try:
    engine, AsyncSessionLocal = _create_engine(settings.DATABASE_URL)
except Exception as e:
    logger.warning(f"Could not initialize primary database engine: {e}. Falling back to SQLite.")
    engine, AsyncSessionLocal = _create_engine("sqlite+aiosqlite:///./skilltwin.db")


def get_session_factory():
    """Always returns the current active AsyncSessionLocal factory."""
    global AsyncSessionLocal
    return AsyncSessionLocal


async def init_db():
    """Initializes database tables on application startup with resilient fallback."""
    global engine, AsyncSessionLocal
    from app.core.db_models import Base

    async def _apply_column_migrations(conn):
        from sqlalchemy import text
        is_sqlite = "sqlite" in str(conn.engine.url)
        migrations = [
            ("goals", "target_level", "TEXT DEFAULT 'Intermediate'"),
            ("goals", "custom_target", "TEXT"),
            ("goals", "target_benchmark", "TEXT"),
            ("learning_paths", "metadata", "TEXT DEFAULT '{}'"),
            ("learning_sections", "metadata", "TEXT DEFAULT '{}'"),
            ("learning_topics", "metadata", "TEXT DEFAULT '{}'"),
            ("learner_topic_progress", "metadata", "TEXT DEFAULT '{}'"),
            ("topic_questions", "metadata", "TEXT DEFAULT '{}'"),
        ]
        for tbl, col, col_def in migrations:
            if is_sqlite:
                sql = f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}"
            else:
                sql = f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {col_def}"
            try:
                await conn.execute(text(sql))
            except Exception:
                pass

    if engine is not None:
        # Step 1: Run column migrations first so existing tables have all required columns
        try:
            async with engine.begin() as conn:
                await _apply_column_migrations(conn)
            logger.info("Database column migrations applied successfully.")
        except Exception as e:
            logger.warning(f"Column migration non-fatal notice: {e}")

        # Step 2: Create any missing tables
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables verified successfully.")
            return
        except Exception as e:
            logger.warning(f"Table verification non-fatal notice: {e}")
            return

    # Fallback to local SQLite only if engine was completely None
    try:
        engine, AsyncSessionLocal = _create_engine("sqlite+aiosqlite:///./skilltwin.db")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _apply_column_migrations(conn)
        logger.info("Local persistent SQLite database synchronized successfully.")
    except Exception as e:
        logger.error(f"Fallback database initialization error: {e}")


async def check_db_health() -> bool:
    """True connectivity check for the database."""
    if engine is None:
        return False
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding database sessions."""
    if AsyncSessionLocal is None:
        yield None
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
