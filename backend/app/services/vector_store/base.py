import math
from typing import Protocol

from app.schemas.chunks import TranscriptChunk
from app.schemas.vectorstore import VectorSearchResult


class VectorStore(Protocol):
    """Persistence for transcript chunk embeddings.

    Implementations store and retrieve vectors and nothing else: embedding
    generation lives above them, so it exists once rather than being duplicated
    per backend.
    """

    async def replace_video_chunks(
        self,
        video_id: str,
        chunks: list[TranscriptChunk],
    ) -> list[str]:
        """Replace every stored chunk for video_id with chunks; return stored ids.

        Replace rather than upsert: chunk ids derive from chunking parameters, so
        upserting after a parameter change leaves the old chunks behind forever and
        retrieval silently mixes two chunkings of the same video.
        """
        ...

    async def similarity_search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        video_id: str | None = None,
    ) -> list[VectorSearchResult]:
        """Return the closest chunks by cosine distance, nearest first."""
        ...


def cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance in pure Python: 1 - cosine_similarity.

    Matches pgvector's `<=>` operator and Chroma's `hnsw:space: cosine`, so the
    value carries the same meaning across every backend.

    Deliberately not numpy — numpy is not a direct dependency and previously arrived
    only via chromadb, which has since been removed.
    """
    if len(a) != len(b):
        raise ValueError(f"embedding dimension mismatch: {len(a)} != {len(b)}")

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0

    return 1.0 - (dot / (norm_a * norm_b))


def chunk_to_result(chunk: TranscriptChunk, distance: float | None) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk.chunk_id,
        video_id=chunk.video_id,
        text=chunk.text,
        start_seconds=chunk.start_seconds,
        end_seconds=chunk.end_seconds,
        segment_indices=chunk.segment_indices,
        distance=distance,
        metadata={
            key: value
            for key, value in chunk.metadata.items()
            if isinstance(value, str | int | float)
        },
    )
