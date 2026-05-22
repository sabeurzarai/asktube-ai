from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    text: str


class TranscriptResponse(BaseModel):
    video_id: str
    language: str | None = None
    source: str = Field(description="Transcript source, such as youtube_transcript_api or whisper.")
    segment_count: int
    full_text: str
    segments: list[TranscriptSegment]
