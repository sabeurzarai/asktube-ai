from app.schemas.chunks import TranscriptChunk
from app.schemas.vectorstore import VectorSearchResult
from app.services.vector_store.base import chunk_to_result, cosine_distance


class InMemoryVectorStore:
    """Process-local vector store for development and tests.

    Replaces the role ChromaDB filled accidentally: letting the suite run with no
    infrastructure. The contract suite is what keeps it honest against pgvector.
    """

    def __init__(self) -> None:
        self._by_video: dict[str, list[TranscriptChunk]] = {}

    async def replace_video_chunks(
        self,
        video_id: str,
        chunks: list[TranscriptChunk],
    ) -> list[str]:
        self._by_video[video_id] = list(chunks)
        return [chunk.chunk_id for chunk in chunks]

    async def similarity_search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        video_id: str | None = None,
    ) -> list[VectorSearchResult]:
        if video_id is not None:
            candidates = self._by_video.get(video_id, [])
        else:
            candidates = [chunk for chunks in self._by_video.values() for chunk in chunks]

        scored: list[tuple[float, TranscriptChunk]] = [
            (cosine_distance(query_embedding, chunk.embedding), chunk)
            for chunk in candidates
            if chunk.embedding is not None
        ]
        scored.sort(key=lambda pair: pair[0])

        return [chunk_to_result(chunk, distance) for distance, chunk in scored[:limit]]
