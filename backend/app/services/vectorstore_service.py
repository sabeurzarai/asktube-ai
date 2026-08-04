import time
from functools import lru_cache

from app.core.config import Settings, settings
from app.analytics.prometheus import EMBEDDING_DURATION, VECTOR_QUERY_DURATION
from app.analytics.service import get_analytics_service
from app.schemas.chunks import TranscriptChunk
from app.schemas.vectorstore import VectorSearchResult
from app.services.embedding_provider import create_embeddings, require_embedding_credentials
from app.services.vector_store.base import VectorStore
from app.services.vector_store.factory import create_vector_store


class VectorStoreService:
    """Embeds chunks and queries, then delegates persistence to a VectorStore.

    Embedding generation lives here rather than in the store implementations so it
    exists once instead of per backend, and so a store can be tested without an
    OpenAI key.
    """

    def __init__(self, config: Settings, store: VectorStore) -> None:
        self.config = config
        self.store = store

    async def upsert_chunks(self, chunks: list[TranscriptChunk]) -> list[str]:
        if not chunks:
            # No video is named, so there is nothing to replace. Returning early
            # rather than clearing anything.
            return []

        video_ids = {chunk.video_id for chunk in chunks}
        if len(video_ids) > 1:
            raise ValueError(
                f"upsert_chunks expects chunks from one video, got {sorted(video_ids)}"
            )
        video_id = video_ids.pop()

        require_embedding_credentials(self.config)

        missing = [chunk for chunk in chunks if chunk.embedding is None]
        if missing:
            embedding_start = time.perf_counter()
            embeddings = create_embeddings(self.config)
            vectors = await embeddings.aembed_documents([chunk.text for chunk in missing])
            embedding_ms = (time.perf_counter() - embedding_start) * 1000
            EMBEDDING_DURATION.observe(embedding_ms / 1000)
            get_analytics_service().safe_track_background(
                get_analytics_service().track_event_safe(
                    "embedding_generated",
                    duration_ms=embedding_ms,
                    metadata_json={
                        "chunk_count": len(missing),
                        "embedding_model": self.config.embedding_model,
                    },
                )
            )
            for chunk, vector in zip(missing, vectors, strict=True):
                chunk.embedding = vector

        insert_start = time.perf_counter()
        stored_ids = await self.store.replace_video_chunks(video_id, chunks)
        insert_ms = (time.perf_counter() - insert_start) * 1000
        get_analytics_service().safe_track_background(
            get_analytics_service().track_event_safe(
                "vector_insert_completed",
                duration_ms=insert_ms,
                metadata_json={
                    "chunk_count": len(chunks),
                    "collection": self.config.resolved_collection_name,
                },
            )
        )
        return stored_ids

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        video_id: str | None = None,
    ) -> list[VectorSearchResult]:
        require_embedding_credentials(self.config)

        embeddings = create_embeddings(self.config)
        embedding_start = time.perf_counter()
        query_embedding = await embeddings.aembed_query(query)
        EMBEDDING_DURATION.observe(time.perf_counter() - embedding_start)

        query_start = time.perf_counter()
        results = await self.store.similarity_search(
            query_embedding, limit=limit, video_id=video_id
        )
        query_ms = (time.perf_counter() - query_start) * 1000
        VECTOR_QUERY_DURATION.observe(query_ms / 1000)
        get_analytics_service().safe_track_background(
            get_analytics_service().track_event_safe(
                "vector_query_completed",
                duration_ms=query_ms,
                metadata_json={
                    "video_id": video_id,
                    "limit": limit,
                    "returned_documents_count": len(results),
                },
            )
        )
        return results


@lru_cache
def get_vectorstore_service() -> VectorStoreService:
    """Built once per process.

    This is a FastAPI dependency and runs per request; the pgvector backend
    allocates a connection pool per construction.
    """
    return VectorStoreService(settings, create_vector_store(settings))
