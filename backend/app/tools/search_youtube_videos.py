from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services.youtube_service import YouTubeService


class SearchYouTubeVideosInput(BaseModel):
    query: str = Field(description="YouTube search query string")
    max_results: int = Field(
        default=10,
        ge=1,
        le=25,
        description="Number of video results to return (1-25)",
    )


def make_search_youtube_videos_tool(service: YouTubeService) -> StructuredTool:
    async def _run(query: str, max_results: int = 10) -> dict:
        result = await service.search_videos(query=query, max_results=max_results)
        return result.model_dump()

    return StructuredTool.from_function(
        coroutine=_run,
        name="search_youtube_videos",
        description=(
            "Search YouTube for videos matching a query. "
            "Returns video titles, descriptions, channel info, durations, and video IDs."
        ),
        args_schema=SearchYouTubeVideosInput,
    )
