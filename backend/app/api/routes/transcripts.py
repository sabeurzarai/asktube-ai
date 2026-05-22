from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.schemas.transcript import TranscriptResponse
from app.services.transcript_service import (
    TranscriptFetchOptions,
    TranscriptService,
    get_transcript_service,
)

router = APIRouter()


@router.get("/{video_id}/transcript", response_model=TranscriptResponse)
async def get_video_transcript(
    video_id: Annotated[
        str,
        Path(
            min_length=6,
            max_length=32,
            pattern=r"^[A-Za-z0-9_-]+$",
            description="YouTube video id.",
        ),
    ],
    language: Annotated[
        str,
        Query(min_length=2, max_length=10, description="Preferred transcript language."),
    ] = "en",
    use_whisper_fallback: Annotated[
        bool,
        Query(description="Use Whisper when YouTube captions are unavailable."),
    ] = True,
    service: TranscriptService = Depends(get_transcript_service),
) -> TranscriptResponse:
    return await service.get_transcript(
        video_id=video_id,
        options=TranscriptFetchOptions(
            language=language,
            use_whisper_fallback=use_whisper_fallback,
        ),
    )
