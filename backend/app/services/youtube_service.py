import re
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import Settings, settings
from app.schemas.search import YouTubeSearchResponse, YouTubeThumbnail, YouTubeVideo


YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
ISO_8601_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


class YouTubeService:
    def __init__(self, config: Settings) -> None:
        self.config = config

    async def search_videos(self, query: str, max_results: int = 10) -> YouTubeSearchResponse:
        if not self.config.youtube_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="YOUTUBE_API_KEY is not configured.",
            )

        search_items = await self._request_search(query=query, max_results=max_results)
        video_ids = [item["id"]["videoId"] for item in search_items if item.get("id", {}).get("videoId")]
        metadata_by_id = await self._request_video_metadata(video_ids)

        videos = [
            self._build_video(item=item, metadata=metadata_by_id.get(item["id"]["videoId"], {}))
            for item in search_items
            if item.get("id", {}).get("videoId")
        ]

        return YouTubeSearchResponse(query=query, count=len(videos), videos=videos)

    async def _request_search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        params = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": max_results,
            "key": self.config.youtube_api_key,
            "safeSearch": "moderate",
            "videoEmbeddable": "true",
        }

        payload = await self._get_json("/search", params=params)
        return payload.get("items", [])

    async def _request_video_metadata(self, video_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not video_ids:
            return {}

        params = {
            "part": "contentDetails,statistics",
            "id": ",".join(video_ids),
            "key": self.config.youtube_api_key,
        }

        payload = await self._get_json("/videos", params=params)
        return {item["id"]: item for item in payload.get("items", []) if item.get("id")}

    async def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.config.youtube_api_base_url}{path}"

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = self._extract_youtube_error(exc.response)
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to reach YouTube Data API.",
            ) from exc

    def _build_video(self, item: dict[str, Any], metadata: dict[str, Any]) -> YouTubeVideo:
        video_id = item["id"]["videoId"]
        snippet = item.get("snippet", {})
        thumbnails = {
            name: YouTubeThumbnail(**thumbnail)
            for name, thumbnail in snippet.get("thumbnails", {}).items()
        }
        best_thumbnail = (
            thumbnails.get("maxres")
            or thumbnails.get("standard")
            or thumbnails.get("high")
            or thumbnails.get("medium")
            or thumbnails.get("default")
        )
        duration = metadata.get("contentDetails", {}).get("duration")
        statistics = metadata.get("statistics", {})

        return YouTubeVideo(
            video_id=video_id,
            title=snippet.get("title", ""),
            description=snippet.get("description", ""),
            channel_id=snippet.get("channelId", ""),
            channel_title=snippet.get("channelTitle", ""),
            published_at=snippet.get("publishedAt", ""),
            thumbnail_url=best_thumbnail.url if best_thumbnail else None,
            thumbnails=thumbnails,
            duration=duration,
            duration_seconds=parse_iso_8601_duration(duration) if duration else None,
            view_count=parse_optional_int(statistics.get("viewCount")),
            like_count=parse_optional_int(statistics.get("likeCount")),
            comment_count=parse_optional_int(statistics.get("commentCount")),
            youtube_url=YOUTUBE_WATCH_URL.format(video_id=video_id),
        )

    @staticmethod
    def _extract_youtube_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return "YouTube Data API request failed."

        error = payload.get("error", {})
        message = error.get("message")

        if isinstance(message, str) and message:
            return message

        return "YouTube Data API request failed."


def parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_iso_8601_duration(duration: str) -> int | None:
    match = ISO_8601_DURATION_PATTERN.match(duration)
    if not match:
        return None

    parts = {key: int(value) if value else 0 for key, value in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def get_youtube_service() -> YouTubeService:
    return YouTubeService(settings)
