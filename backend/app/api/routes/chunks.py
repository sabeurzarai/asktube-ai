from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.core.config import settings
from app.schemas.chunks import ChunkTranscriptRequest, ChunkTranscriptResponse
from app.services.chunking_service import ChunkingOptions, ChunkingService, get_chunking_service
from app.services.transcript_service import (
    TranscriptFetchOptions,
    TranscriptService,
    get_transcript_service,
)

router = APIRouter()


@router.post("/transcripts/chunks", response_model=ChunkTranscriptResponse)
async def chunk_transcript(
    request: ChunkTranscriptRequest,
    service: ChunkingService = Depends(get_chunking_service),
) -> ChunkTranscriptResponse:
    chunks, embedding_model = await service.chunk_transcript(
        transcript=request.transcript,
        options=ChunkingOptions(
            max_chunk_chars=request.max_chunk_chars or settings.chunk_max_chars,
            overlap_segments=(
                request.overlap_segments
                if request.overlap_segments is not None
                else settings.chunk_overlap_segments
            ),
            include_embeddings=request.include_embeddings,
        ),
    )

    return ChunkTranscriptResponse(
        video_id=request.transcript.video_id,
        source=request.transcript.source,
        language=request.transcript.language,
        chunk_count=len(chunks),
        embedding_model=embedding_model,
        chunks=chunks,
    )


@router.get("/videos/{video_id}/chunks", response_model=ChunkTranscriptResponse)
async def chunk_video_transcript(
    video_id: Annotated[
        str,
        Path(
            min_length=6,
            max_length=32,
            pattern=r"^[A-Za-z0-9_-]+$",
            description="YouTube video id.",
        ),
    ],
    language: Annotated[str, Query(min_length=2, max_length=10)] = "en",
    include_embeddings: bool = Query(default=False),
    max_chunk_chars: int = Query(default=1200, ge=300, le=4000),
    overlap_segments: int = Query(default=1, ge=0, le=5),
    transcript_service: TranscriptService = Depends(get_transcript_service),
    chunking_service: ChunkingService = Depends(get_chunking_service),
) -> ChunkTranscriptResponse:
    transcript = await transcript_service.get_transcript(
        video_id=video_id,
        options=TranscriptFetchOptions(language=language, use_whisper_fallback=True),
    )
    chunks, embedding_model = await chunking_service.chunk_transcript(
        transcript=transcript,
        options=ChunkingOptions(
            max_chunk_chars=max_chunk_chars,
            overlap_segments=overlap_segments,
            include_embeddings=include_embeddings,
        ),
    )

    return ChunkTranscriptResponse(
        video_id=video_id,
        source=transcript.source,
        language=transcript.language,
        chunk_count=len(chunks),
        embedding_model=embedding_model,
        chunks=chunks,
    )
