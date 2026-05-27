from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    session_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    page: Mapped[str | None] = mapped_column(String(240), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class VideoMetric(Base):
    __tablename__ = "video_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    video_id: Mapped[str] = mapped_column(String(40), index=True)
    processing_time: Mapped[float] = mapped_column(Float, default=0)
    transcript_time: Mapped[float] = mapped_column(Float, default=0)
    embedding_time: Mapped[float] = mapped_column(Float, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    whisper_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class ChatMetric(Base):
    __tablename__ = "chat_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    questions_count: Mapped[int] = mapped_column(Integer, default=1)
    avg_response_time: Mapped[float] = mapped_column(Float, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    followup_questions: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class RAGMetric(Base):
    __tablename__ = "rag_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    query: Mapped[str] = mapped_column(Text)
    retrieval_latency: Mapped[float] = mapped_column(Float, default=0)
    generation_latency: Mapped[float] = mapped_column(Float, default=0)
    chunks_retrieved: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str] = mapped_column(String(120))
    citation_coverage: Mapped[float] = mapped_column(Float, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    context_tokens: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    response_length: Mapped[int] = mapped_column(Integer, default=0)
    hallucination_warning: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
