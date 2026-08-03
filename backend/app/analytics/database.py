from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

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
        # Prepared statements do not survive a transaction pooler, and disabling
        # asyncpg's own cache (statement_cache_size=0) is NOT enough on its own:
        # SQLAlchemy's asyncpg dialect keeps a second layer on top of that --
        # its _prepare step always calls connection.prepare(..., name=...) via
        # a numeric name generator, and prepared_statement_cache_size still
        # defaults to 100 unless set here too. Two pooled client connections
        # multiplexed onto one pooler backend can then collide on the same
        # generated "__asyncpg_stmt_N__" name. All three settings below are
        # required together, and applied unconditionally to every Postgres
        # engine this app builds -- not only when a pooler happens to be in
        # front of it, since the SQLAlchemy-side collision isn't pooler-specific.
        kwargs["connect_args"] = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        }

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
    """Create tables automatically for local SQLite only.

    Postgres schema is owned by Alembic. Running create_all there as well would
    mean two mechanisms managing one schema, which drifts without warning.
    """
    if settings.resolved_analytics_url.startswith("postgresql"):
        return

    from app.analytics.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
