import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.analytics.models import Base

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


class NotAScratchDatabase(RuntimeError):
    """Raised when a destructive fixture is aimed at a database it must not wipe."""


def reject_non_scratch_database(
    test_database_url: str | None,
    app_database_url: str | None,
    existing_row_count: int,
    table_name: str = "transcript_chunks",
) -> None:
    """Refuse to run a destructive database fixture against real data.

    This fixture deletes every row in the target table (and, for the pgvector
    contract suite, alters the embedding column). A docstring warning is not a
    safeguard: this project's own verification steps instruct the operator to run

        $env:TEST_DATABASE_URL = $env:DATABASE_URL

    which aims it squarely at production. That is not a hypothetical — it happened,
    and it emptied the live table.

    Pure function so the guard itself is testable without a database, which matters
    for a check whose whole job is to fire when no test database is present.
    """
    if app_database_url and test_database_url == app_database_url:
        raise NotAScratchDatabase(
            f"TEST_DATABASE_URL points at the same database as DATABASE_URL. This "
            f"fixture deletes every row in {table_name}. Point it at a scratch "
            "database."
        )

    if existing_row_count:
        raise NotAScratchDatabase(
            f"{table_name} already holds {existing_row_count} row(s). This "
            "fixture deletes every row, so it refuses to run against a database "
            "containing data it did not create. Empty the table deliberately, or "
            "point TEST_DATABASE_URL at a scratch database."
        )


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def patched_db(test_engine, monkeypatch):
    """Patches the module-level session factory to use the in-memory test engine."""
    import app.analytics.database as db_module

    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", factory)
    yield factory
