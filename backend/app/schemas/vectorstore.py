from pydantic import BaseModel, Field

from app.schemas.transcript import TranscriptResponse


class IngestTranscriptRequest(BaseModel):
    transcript: TranscriptResponse
    max_chunk_chars: int | None = Field(default=None, ge=300, le=4000)
    overlap_segments: int | None = Field(default=None, ge=0, le=5)


class IngestVideoResponse(BaseModel):
    video_id: str
    collection_name: str
    chunk_count: int
    embedding_model: str
    stored_chunk_ids: list[str]


class VectorSearchResult(BaseModel):
    chunk_id: str
    video_id: str
    text: str
    start_seconds: float
    end_seconds: float
    segment_indices: list[int]
    distance: float | None = None
    metadata: dict[str, str | int | float]


class VectorSearchResponse(BaseModel):
    query: str
    video_id: str | None = None
    collection_name: str
    result_count: int
    results: list[VectorSearchResult]
