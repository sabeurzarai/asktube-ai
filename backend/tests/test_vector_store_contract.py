import pytest

from app.schemas.chunks import TranscriptChunk
from app.services.vector_store import InMemoryVectorStore


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


# Task 6 appends the pgvector backend here. Test bodies stay unchanged.
@pytest.fixture(params=["memory"])
def store(request):
    if request.param == "memory":
        return InMemoryVectorStore()
    raise AssertionError(f"unknown backend {request.param}")


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
