import os

import pytest

# Runs only when a real database is available. Mirrors the existing convention
# for local-embedding tests: absent extras/infrastructure means skip, not fail.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set; skipping migration test",
)


async def test_migrations_create_analytics_tables():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public'"
            )
        )
        tables = {row[0] for row in result}
    await engine.dispose()

    assert {"analytics_events", "video_metrics", "chat_metrics", "rag_metrics"} <= tables
