import pytest

from app.core.config import Settings
from app.schemas.chunks import TranscriptChunk
from app.services.vector_store import InMemoryVectorStore
from app.services.vectorstore_service import (
    VectorStoreService,
    get_vectorstore_service,
)


def make_orchestrator_chunk(video_id: str, index: int, embedding=None) -> TranscriptChunk:
    return TranscriptChunk(
        chunk_id=f"{video_id}-{index}",
        index=index,
        video_id=video_id,
        text=f"chunk {index}",
        start_seconds=float(index),
        end_seconds=float(index + 1),
        segment_indices=[index],
        token_estimate=3,
        metadata={"source": "captions", "language": "en"},
        embedding=embedding,
    )


def make_service(store=None) -> VectorStoreService:
    return VectorStoreService(Settings(_env_file=None), store or InMemoryVectorStore())


async def test_upsert_with_no_chunks_is_a_noop_and_returns_empty():
    # Must NOT clear anything: no video is named, so there is nothing to replace.
    store = InMemoryVectorStore()
    await store.replace_video_chunks("vid1", [make_orchestrator_chunk("vid1", 0, [1.0, 0.0])])
    service = make_service(store)

    assert await service.upsert_chunks([]) == []
    assert len(await store.similarity_search([1.0, 0.0], limit=5, video_id="vid1")) == 1


async def test_upsert_rejects_chunks_spanning_multiple_videos():
    service = make_service()
    chunks = [make_orchestrator_chunk("vid1", 0, [1.0, 0.0]), make_orchestrator_chunk("vid2", 0, [1.0, 0.0])]
    with pytest.raises(ValueError, match="vid1"):
        await service.upsert_chunks(chunks)


async def test_upsert_replaces_previous_chunks_for_the_video():
    store = InMemoryVectorStore()
    service = make_service(store)
    await service.upsert_chunks([make_orchestrator_chunk("vid1", 0, [1.0, 0.0])])
    await service.upsert_chunks([make_orchestrator_chunk("vid1", 9, [1.0, 0.0])])

    results = await store.similarity_search([1.0, 0.0], limit=10, video_id="vid1")
    assert [r.chunk_id for r in results] == ["vid1-9"]


async def test_chunks_that_already_have_embeddings_are_not_re_embedded(monkeypatch):
    calls = {"count": 0}

    class FakeEmbeddings:
        async def aembed_documents(self, texts):
            calls["count"] += 1
            return [[1.0, 0.0] for _ in texts]

        async def aembed_query(self, text):
            calls["count"] += 1
            return [1.0, 0.0]

    import app.services.vectorstore_service as module

    monkeypatch.setattr(module, "create_embeddings", lambda _config: FakeEmbeddings())
    service = make_service()
    await service.upsert_chunks([make_orchestrator_chunk("vid1", 0, [1.0, 0.0])])
    assert calls["count"] == 0


def test_vector_store_is_built_once_not_per_request():
    get_vectorstore_service.cache_clear()
    first = get_vectorstore_service()
    second = get_vectorstore_service()
    # Same object: a FastAPI Depends runs per request, and the pgvector backend
    # allocates a connection pool per construction.
    assert first is second


def test_get_vectorstore_service_returns_vectorstoreservice_when_backend_unset_and_no_database(monkeypatch):
    # Task 2b-ii: when VECTOR_BACKEND is unset, it now derives from DATABASE_URL.
    # Unset + no DATABASE_URL → memory backend → VectorStoreService (not Chroma).
    # The chroma selection branch in get_vectorstore_service is now unreachable.
    import app.services.vectorstore_service as module

    # Patch the settings object, not the environment: `settings` is an lru_cached
    # singleton built at import, so delenv() would not affect it and the test would
    # fail for anyone running the suite with DATABASE_URL exported.
    monkeypatch.setattr(module.settings, "vector_backend", None)
    monkeypatch.setattr(module.settings, "database_url", None)
    get_vectorstore_service.cache_clear()
    try:
        service = get_vectorstore_service()
        assert isinstance(service, VectorStoreService)
    finally:
        get_vectorstore_service.cache_clear()


def test_get_vectorstore_service_returns_vectorstoreservice_for_memory_backend(monkeypatch):
    import app.services.vectorstore_service as module

    monkeypatch.setattr(module.settings, "vector_backend", "memory")
    get_vectorstore_service.cache_clear()
    try:
        service = get_vectorstore_service()
        assert isinstance(service, VectorStoreService)
    finally:
        get_vectorstore_service.cache_clear()
