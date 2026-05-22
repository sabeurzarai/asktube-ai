from pydantic import BaseModel, Field


class YouTubeThumbnail(BaseModel):
    url: str
    width: int | None = None
    height: int | None = None


class YouTubeVideo(BaseModel):
    video_id: str = Field(description="YouTube video id.")
    title: str
    description: str
    channel_id: str
    channel_title: str
    published_at: str
    thumbnail_url: str | None = None
    thumbnails: dict[str, YouTubeThumbnail] = Field(default_factory=dict)
    duration: str | None = Field(default=None, description="ISO 8601 duration from YouTube.")
    duration_seconds: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    youtube_url: str


class YouTubeSearchResponse(BaseModel):
    query: str
    count: int
    videos: list[YouTubeVideo]
