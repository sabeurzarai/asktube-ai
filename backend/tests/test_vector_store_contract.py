import os

import pytest

from app.core.config import settings
from app.schemas.chunks import TranscriptChunk
from app.services.vector_store import InMemoryVectorStore, PgVectorStore

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

BACKENDS = ["memory"]
if TEST_DATABASE_URL:
    BACKENDS.append("pgvector")

# The contract vectors are 3-dimensional for readability; production is 1536.
# The pgvector fixture narrows the column for the run and restores it after.
CONTRACT_DIMENSIONS = 3
PRODUCTION_DIMENSIONS = 1536


class NotAScratchDatabase(RuntimeError):
    """Raised when the pgvector fixture is aimed at a database it must not wipe."""


def reject_non_scratch_database(
    test_database_url: str | None,
    app_database_url: str | None,
    existing_row_count: int,
) -> None:
    """Refuse to run the destructive pgvector fixture against real data.

    This fixture deletes every row in transcript_chunks and alters the embedding
    column. A docstring warning is not a safeguard: this project's own verification
    steps instruct the operator to run

        $env:TEST_DATABASE_URL = $env:DATABASE_URL

    which aims it squarely at production. That is not a hypothetical — it happened,
    and it emptied the live table.

    Pure function so the guard itself is testable without a database, which matters
    for a check whose whole job is to fire when no test database is present.
    """
    if app_database_url and test_database_url == app_database_url:
        raise NotAScratchDatabase(
            "TEST_DATABASE_URL points at the same database as DATABASE_URL. This "
            "fixture deletes every row in transcript_chunks and alters the embedding "
            "column. Point it at a scratch database."
        )

    if existing_row_count:
        raise NotAScratchDatabase(
            f"transcript_chunks already holds {existing_row_count} row(s). This "
            "fixture deletes every row, so it refuses to run against a database "
            "containing data it did not create. Empty the table deliberately, or "
            "point TEST_DATABASE_URL at a scratch database."
        )


@pytest.fixture(params=BACKENDS)
async def store(request):
    """Yield each backend in turn.

    The pgvector branch is destructive: it deletes every row in transcript_chunks
    and narrows the embedding column for the run. `reject_non_scratch_database`
    below refuses to proceed unless the target is demonstrably disposable.
    """
    if request.param == "memory":
        yield InMemoryVectorStore()
        return

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # Check BEFORE deleting anything. Reading first costs one round trip and is the
    # difference between a guard and an apology.
    async with factory() as session:
        existing = (
            await session.execute(text("select count(*) from transcript_chunks"))
        ).scalar_one()
    try:
        reject_non_scratch_database(TEST_DATABASE_URL, settings.database_url, existing)
    except NotAScratchDatabase:
        await engine.dispose()
        raise

    async with factory() as session:
        async with session.begin():
            # Each test starts empty: the contract asserts ordering and isolation,
            # which leftover rows would silently break.
            await session.execute(text("delete from transcript_chunks"))
            await session.execute(
                text(
                    "alter table transcript_chunks "
                    f"alter column embedding type vector({CONTRACT_DIMENSIONS})"
                )
            )

    try:
        yield PgVectorStore(factory, embedding_dimensions=CONTRACT_DIMENSIONS)
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(text("delete from transcript_chunks"))
                await session.execute(
                    text(
                        "alter table transcript_chunks "
                        f"alter column embedding type vector({PRODUCTION_DIMENSIONS})"
                    )
                )
        await engine.dispose()


def make_chunk(video_id: str, index: int, embedding: list[float], text: str = "") -> TranscriptChunk:
    return TranscriptChunk(
        chunk_id=f"{video_id}-{index}",
        index=index,
        video_id=video_id,
        text=text or f"chunk {index} of {video_id}",
        start_seconds=float(index * 10),
        end_seconds=float(index * 10 + 10),
        segment_indices=[index],
        token_estimate=5,
        metadata={"source": "captions", "language": "en"},
        embedding=embedding,
    )


async def test_stored_chunk_is_retrievable(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    results = await store.similarity_search([1.0, 0.0, 0.0], limit=5)
    assert [r.chunk_id for r in results] == ["vid1-0"]


async def test_results_are_ordered_nearest_first(store):
    await store.replace_video_chunks(
        "vid1",
        [
            make_chunk("vid1", 0, [0.0, 1.0, 0.0]),   # orthogonal to query
            make_chunk("vid1", 1, [1.0, 0.0, 0.0]),   # identical to query
        ],
    )
    results = await store.similarity_search([1.0, 0.0, 0.0], limit=5)
    assert [r.chunk_id for r in results] == ["vid1-1", "vid1-0"]
    assert results[0].distance < results[1].distance


async def test_limit_is_respected(store):
    # Insert chunks in REVERSED order (4, 3, 2, 1, 0) so that a backend returning
    # "the first two inserted" would fail. Only backends that sort before limiting
    # correctly return [vid1-0, vid1-1] (the two nearest by cosine distance).
    await store.replace_video_chunks(
        "vid1",
        [make_chunk("vid1", i, [1.0, float(i) / 10, 0.0]) for i in reversed(range(5))],
    )
    results = await store.similarity_search([1.0, 0.0, 0.0], limit=2)
    assert len(results) == 2
    assert [r.chunk_id for r in results] == ["vid1-0", "vid1-1"]


async def test_video_id_filter_isolates_videos(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid2", [make_chunk("vid2", 0, [1.0, 0.0, 0.0])])

    results = await store.similarity_search([1.0, 0.0, 0.0], limit=10, video_id="vid1")
    assert [r.video_id for r in results] == ["vid1"]

    unfiltered = await store.similarity_search([1.0, 0.0, 0.0], limit=10)
    assert {r.video_id for r in unfiltered} == {"vid1", "vid2"}


async def test_reingest_replaces_rather_than_accumulates(store):
    """The stale-chunk bug: re-chunking changes ids, and upsert would keep both sets."""
    await store.replace_video_chunks(
        "vid1",
        [make_chunk("vid1", 0, [1.0, 0.0, 0.0]), make_chunk("vid1", 1, [0.0, 1.0, 0.0])],
    )
    # Re-ingest with different chunking: one chunk, a different id.
    replacement = make_chunk("vid1", 99, [1.0, 0.0, 0.0])
    await store.replace_video_chunks("vid1", [replacement])

    results = await store.similarity_search([1.0, 0.0, 0.0], limit=10, video_id="vid1")
    assert [r.chunk_id for r in results] == ["vid1-99"]


async def test_replacing_one_video_leaves_others_untouched(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid2", [make_chunk("vid2", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 7, [1.0, 0.0, 0.0])])

    remaining = await store.similarity_search([1.0, 0.0, 0.0], limit=10, video_id="vid2")
    assert [r.chunk_id for r in remaining] == ["vid2-0"]


async def test_search_on_empty_store_returns_empty_list(store):
    assert await store.similarity_search([1.0, 0.0, 0.0], limit=5) == []


async def test_replace_with_empty_list_clears_the_video(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid1", [])
    assert await store.similarity_search([1.0, 0.0, 0.0], limit=5, video_id="vid1") == []


async def test_result_carries_timestamps_and_metadata(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 3, [1.0, 0.0, 0.0])])
    result = (await store.similarity_search([1.0, 0.0, 0.0], limit=1))[0]
    assert result.start_seconds == 30.0
    assert result.end_seconds == 40.0
    assert result.segment_indices == [3]
    assert result.metadata["source"] == "captions"


# ── The guard itself ──────────────────────────────────────────────────────────
# Tested as a pure function: a safeguard whose job is to fire when no scratch
# database is available must not itself require one.


def test_guard_rejects_pointing_at_the_application_database():
    with pytest.raises(NotAScratchDatabase, match="same database as DATABASE_URL"):
        reject_non_scratch_database(
            test_database_url="postgresql+asyncpg://u:p@host/db",
            app_database_url="postgresql+asyncpg://u:p@host/db",
            existing_row_count=0,
        )


def test_guard_rejects_a_table_that_already_holds_data():
    # The real incident: the table held a demo video's chunks and the fixture
    # deleted them. Row count alone is enough to refuse.
    with pytest.raises(NotAScratchDatabase, match="10 row"):
        reject_non_scratch_database(
            test_database_url="postgresql+asyncpg://u:p@scratch/db",
            app_database_url="postgresql+asyncpg://u:p@prod/db",
            existing_row_count=10,
        )


def test_guard_allows_a_distinct_and_empty_database():
    reject_non_scratch_database(
        test_database_url="postgresql+asyncpg://u:p@scratch/db",
        app_database_url="postgresql+asyncpg://u:p@prod/db",
        existing_row_count=0,
    )


def test_guard_allows_an_empty_database_when_the_app_has_none_configured():
    # Local checkouts have no DATABASE_URL; the row-count check still applies.
    reject_non_scratch_database(
        test_database_url="postgresql+asyncpg://u:p@scratch/db",
        app_database_url=None,
        existing_row_count=0,
    )
