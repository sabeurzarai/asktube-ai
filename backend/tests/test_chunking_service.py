import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.schemas.transcript import TranscriptResponse, TranscriptSegment
from app.services.chunking_service import (
    ChunkingOptions,
    ChunkingService,
    build_semantic_chunks,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_transcript() -> TranscriptResponse:
    return TranscriptResponse(
        video_id="video123",
        language="en",
        source="youtube_transcript_api",
        segment_count=4,
        full_text="Alpha concept. Beta detail. Gamma explanation. Delta wrap.",
        segments=[
            TranscriptSegment(
                index=0,
                start_seconds=0.0,
                end_seconds=4.0,
                duration_seconds=4.0,
                text="Alpha concept.",
            ),
            TranscriptSegment(
                index=1,
                start_seconds=4.0,
                end_seconds=8.0,
                duration_seconds=4.0,
                text="Beta detail.",
            ),
            TranscriptSegment(
                index=2,
                start_seconds=8.0,
                end_seconds=12.0,
                duration_seconds=4.0,
                text="Gamma explanation.",
            ),
            TranscriptSegment(
                index=3,
                start_seconds=12.0,
                end_seconds=16.0,
                duration_seconds=4.0,
                text="Delta wrap.",
            ),
        ],
    )


def test_build_semantic_chunks_preserves_timestamps() -> None:
    chunks = build_semantic_chunks(
        transcript=make_transcript(),
        max_chunk_chars=36,
        overlap_segments=1,
    )

    assert len(chunks) >= 2
    assert chunks[0].video_id == "video123"
    assert chunks[0].start_seconds == 0.0
    assert chunks[0].segment_indices == [0, 1]
    assert chunks[1].segment_indices[0] == 1
    assert chunks[0].metadata["source"] == "youtube_transcript_api"
    assert chunks[0].embedding is None


@pytest.mark.anyio
async def test_embedding_generation_requires_openai_key() -> None:
    service = ChunkingService(
        Settings(
            OPENAI_API_KEY="",
            YOUTUBE_API_KEY="",
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.chunk_transcript(
            transcript=make_transcript(),
            options=ChunkingOptions(
                max_chunk_chars=1200,
                overlap_segments=1,
                include_embeddings=True,
            ),
        )

    assert exc_info.value.status_code == 503
