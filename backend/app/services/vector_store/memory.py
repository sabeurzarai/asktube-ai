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

    async def list_video_chunks(self, video_id: str) -> list[TranscriptChunk]:
        # Deep copies, not the stored objects: TranscriptChunk is mutable and its
        # segment_indices and metadata are a list and a dict, so a shallow copy
        # would still let a caller mutate the store's internals in place.
        # Clearing the embedding matches pgvector, which never selects that
        # column - the contract is that both backends return the same thing.
        return [
            chunk.model_copy(update={"embedding": None}, deep=True)
            for chunk in sorted(self._by_video.get(video_id, []), key=lambda item: item.index)
        ]
