import os

import pytest

# Runs only when a real database is available. Mirrors the existing convention
# for local-embedding tests: absent extras/infrastructure means skip, not fail.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set; skipping migration test",
)


def test_migrations_create_analytics_tables():
    # Synchronous on purpose: pytest.ini sets asyncio_mode = auto, which would
    # otherwise run this test inside an already-running event loop, and
    # alembic's online migration path internally calls asyncio.run(...) —
    # which raises "cannot be called from a running event loop" if one is
    # already active. Keeping this test sync means no loop is running when
    # command.upgrade() reaches that call.
    import asyncio

    import sqlalchemy
    from sqlalchemy.ext.asyncio import create_async_engine

    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    # Alembic's Config wraps configparser.ConfigParser with BasicInterpolation,
    # which raises ValueError on a lone '%' -- and percent-encoded passwords
    # (e.g. p%40ss) contain exactly that. Escaping to %% here is undone by
    # ConfigParser's own get() reader, so the engine still receives the
    # correct, unescaped URL. Mirrors backend/alembic/env.py.
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    command.upgrade(config, "head")

    async def _get_tables() -> set[str]:
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_conn: set(sqlalchemy.inspect(sync_conn).get_table_names())
            )
        await engine.dispose()
        return tables

    tables = asyncio.run(_get_tables())

    assert {"analytics_events", "video_metrics", "chat_metrics", "rag_metrics"} <= tables
