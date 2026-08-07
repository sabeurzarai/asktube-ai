import os

import pytest

from app.core.config import settings
from app.schemas.chunks import TranscriptChunk
from app.services.vector_store import InMemoryVectorStore, PgVectorStore
from tests.conftest import NotAScratchDatabase, reject_non_scratch_database

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

BACKENDS = ["memory"]
if TEST_DATABASE_URL:
    BACKENDS.append("pgvector")

# The contract vectors are 3-dimensional for readability; production is 1536.
# The pgvector fixture narrows the column for the run and restores it after.
CONTRACT_DIMENSIONS = 3
PRODUCTION_DIMENSIONS = 1536


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
        reject_non_scratch_database(
            TEST_DATABASE_URL,
            settings.database_url,
            existing,
            table_name="transcript_chunks",
        )
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


async def test_list_video_chunks_returns_every_chunk_in_index_order(store):
    # Inserted out of order so a backend that returns insertion order fails.
    await store.replace_video_chunks(
        "vid1",
        [make_chunk("vid1", i, [1.0, float(i) / 10, 0.0]) for i in (2, 0, 1)],
    )

    chunks = await store.list_video_chunks("vid1")

    assert [c.index for c in chunks] == [0, 1, 2]
    assert [c.chunk_id for c in chunks] == ["vid1-0", "vid1-1", "vid1-2"]


async def test_list_video_chunks_isolates_videos(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid2", [make_chunk("vid2", 0, [0.0, 1.0, 0.0])])

    assert [c.video_id for c in await store.list_video_chunks("vid1")] == ["vid1"]
    assert [c.video_id for c in await store.list_video_chunks("vid2")] == ["vid2"]


async def test_list_video_chunks_returns_empty_for_unknown_video(store):
    # Empty, not an error: an un-ingested video is an ordinary state, and the
    # summarisation path relies on being able to fall through quietly.
    assert await store.list_video_chunks("never-ingested") == []


async def test_list_video_chunks_preserves_timestamps_and_text(store):
    await store.replace_video_chunks(
        "vid1", [make_chunk("vid1", 3, [1.0, 0.0, 0.0], text="the important sentence")]
    )

    chunk = (await store.list_video_chunks("vid1"))[0]

    assert chunk.text == "the important sentence"
    assert chunk.start_seconds == 30.0
    assert chunk.end_seconds == 40.0
    assert chunk.segment_indices == [3]
