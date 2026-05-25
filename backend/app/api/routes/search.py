from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.schemas.search import YouTubeSearchResponse
from app.services.youtube_service import YouTubeService, get_youtube_service

router = APIRouter()


@router.get("", response_model=YouTubeSearchResponse)
async def search_youtube_videos(
    q: Annotated[
        str,
        Query(
            min_length=2,
            max_length=120,
            description="Search query for YouTube videos.",
            examples=["nutrition for muscle growth"],
        ),
    ],
    max_results: Annotated[
        int,
        Query(ge=1, le=25, description="Maximum number of videos to return."),
    ] = 10,
    duration_filter: Annotated[
        Literal["any", "under_10", "under_30", "under_60", "over_60"],
        Query(description="Optional video length filter."),
    ] = "any",
    service: YouTubeService = Depends(get_youtube_service),
) -> YouTubeSearchResponse:
    return await service.search_videos(
        query=q,
        max_results=max_results,
        duration_filter=duration_filter,
    )
