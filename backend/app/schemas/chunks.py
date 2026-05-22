from pydantic import BaseModel, Field

from app.schemas.transcript import TranscriptResponse


class TranscriptChunk(BaseModel):
    chunk_id: str
    index: int
    video_id: str
    text: str
    start_seconds: float
    end_seconds: float
    segment_indices: list[int]
    token_estimate: int
    metadata: dict[str, str | int | float | list[int]]
    embedding: list[float] | None = Field(
        default=None,
        description="Embedding vector. Omitted unless include_embeddings=true.",
    )


class ChunkTranscriptRequest(BaseModel):
    transcript: TranscriptResponse
    include_embeddings: bool = False
    max_chunk_chars: int | None = Field(default=None, ge=300, le=4000)
    overlap_segments: int | None = Field(default=None, ge=0, le=5)


class ChunkTranscriptResponse(BaseModel):
    video_id: str
    source: str
    language: str | None = None
    chunk_count: int
    embedding_model: str | None = None
    chunks: list[TranscriptChunk]
