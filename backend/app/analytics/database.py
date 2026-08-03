from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, settings


def build_engine_kwargs(url: str, config: Settings) -> dict[str, Any]:
    """Engine options per driver.

    SQLite's async pool takes no size, and statement_cache_size is an asyncpg-only
    connect arg, so neither can be applied unconditionally.
    """
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}

    if url.startswith("postgresql"):
        kwargs["pool_size"] = config.db_pool_size
        kwargs["max_overflow"] = config.db_max_overflow
        # Prepared statements do not survive a transaction pooler. Left enabled,
        # this fails intermittently with DuplicatePreparedStatementError under
        # concurrency rather than failing loudly at startup.
        kwargs["connect_args"] = {"statement_cache_size": 0}

    return kwargs


engine = create_async_engine(
    settings.resolved_analytics_url,
    **build_engine_kwargs(settings.resolved_analytics_url, settings),
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def analytics_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_analytics_db() -> None:
    from app.analytics.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
