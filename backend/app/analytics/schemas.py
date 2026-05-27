from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AnalyticsEventCreate(BaseModel):
    event_type: str = Field(min_length=2, max_length=120)
    session_id: str | None = None
    user_id: str | None = None
    page: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class VideoMetricCreate(BaseModel):
    video_id: str
    processing_time: float = 0
    transcript_time: float = 0
    embedding_time: float = 0
    chunk_count: int = 0
    whisper_used: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ChatMetricCreate(BaseModel):
    session_id: str
    questions_count: int = 1
    avg_response_time: float = 0
    tokens_used: int = 0
    followup_questions: int = 0
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RAGMetricCreate(BaseModel):
    query: str
    retrieval_latency: float = 0
    generation_latency: float = 0
    chunks_retrieved: int = 0
    embedding_model: str
    citation_coverage: float = 0
    context_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    response_length: int = 0
    hallucination_warning: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class AnalyticsAccepted(BaseModel):
    status: str = "accepted"


class MetricPoint(BaseModel):
    label: str
    value: float


class AnalyticsOverview(BaseModel):
    daily_active_users: int
    weekly_active_users: int
    questions_today: int
    videos_processed_today: int
    avg_session_time_ms: float
    avg_processing_time_ms: float
    voice_usage_rate: float
    search_success_rate: float


class AnalyticsDashboard(BaseModel):
    generated_at: datetime
    overview: AnalyticsOverview
    ai_metrics: dict[str, list[MetricPoint] | float | int]
    pipeline_metrics: dict[str, list[MetricPoint] | float | int]
    ux_metrics: dict[str, float | int]
    business_metrics: dict[str, float | int | list[MetricPoint]]
    recent_events: list[dict[str, Any]]
