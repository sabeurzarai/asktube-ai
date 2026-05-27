import asyncio
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from collections.abc import Awaitable
from typing import Any

from sqlalchemy import distinct, func, select

from app.analytics.database import analytics_session
from app.analytics.models import AnalyticsEvent, ChatMetric, RAGMetric, VideoMetric
from app.analytics.schemas import (
    AnalyticsDashboard,
    AnalyticsEventCreate,
    AnalyticsOverview,
    ChatMetricCreate,
    MetricPoint,
    RAGMetricCreate,
    VideoMetricCreate,
)
from app.core.config import Settings, settings


class AnalyticsService:
    def __init__(self, config: Settings) -> None:
        self.config = config

    async def track_event(self, event: AnalyticsEventCreate) -> None:
        await self._write(AnalyticsEvent(**event.model_dump()))

    async def track_event_safe(
        self,
        event_type: str,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        page: str | None = None,
        duration_ms: float | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        await self.safe_track(
            self.track_event(
                AnalyticsEventCreate(
                    event_type=event_type,
                    session_id=session_id,
                    user_id=user_id,
                    page=page,
                    duration_ms=duration_ms,
                    metadata_json=metadata_json or {},
                )
            )
        )

    async def track_video_metric(self, metric: VideoMetricCreate) -> None:
        await self._write(VideoMetric(**metric.model_dump()))

    async def track_chat_metric(self, metric: ChatMetricCreate) -> None:
        await self._write(ChatMetric(**metric.model_dump()))

    async def track_rag_metric(self, metric: RAGMetricCreate) -> None:
        await self._write(RAGMetric(**metric.model_dump()))

    async def safe_track(self, awaitable: Awaitable[Any]) -> None:
        if not self.config.analytics_enabled:
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            return
        try:
            await awaitable
        except Exception:
            return

    def safe_track_background(self, awaitable) -> None:
        if not self.config.analytics_enabled:
            return
        try:
            asyncio.create_task(self.safe_track(awaitable))
        except RuntimeError:
            return

    async def dashboard(self) -> AnalyticsDashboard:
        now = datetime.now(timezone.utc)
        day_start = now - timedelta(days=1)
        week_start = now - timedelta(days=7)

        async with analytics_session() as session:
            dau = await scalar_count(
                session,
                select(func.count(distinct(AnalyticsEvent.user_id))).where(
                    AnalyticsEvent.timestamp >= day_start,
                    AnalyticsEvent.user_id.is_not(None),
                ),
            )
            wau = await scalar_count(
                session,
                select(func.count(distinct(AnalyticsEvent.user_id))).where(
                    AnalyticsEvent.timestamp >= week_start,
                    AnalyticsEvent.user_id.is_not(None),
                ),
            )
            questions_today = await scalar_count(
                session,
                select(func.coalesce(func.sum(ChatMetric.questions_count), 0)).where(ChatMetric.timestamp >= day_start),
            )
            videos_today = await scalar_count(
                session,
                select(func.count(VideoMetric.id)).where(VideoMetric.created_at >= day_start),
            )
            avg_session = await scalar_float(
                session,
                select(func.coalesce(func.avg(AnalyticsEvent.duration_ms), 0)).where(
                    AnalyticsEvent.event_type == "session_ended",
                    AnalyticsEvent.timestamp >= week_start,
                ),
            )
            avg_processing = await scalar_float(
                session,
                select(func.coalesce(func.avg(VideoMetric.processing_time), 0)).where(VideoMetric.created_at >= week_start),
            )

            total_searches = await event_count(session, "search_submitted", week_start)
            completed_searches = await event_count(session, "search_completed", week_start)
            voice_started = await event_count(session, "voice_search_started", week_start)
            voice_completed = await event_count(session, "voice_search_completed", week_start)

            rag_rows = (
                await session.execute(
                    select(RAGMetric).where(RAGMetric.timestamp >= week_start).order_by(RAGMetric.timestamp.asc())
                )
            ).scalars().all()
            video_rows = (
                await session.execute(
                    select(VideoMetric).where(VideoMetric.created_at >= week_start).order_by(VideoMetric.created_at.asc())
                )
            ).scalars().all()
            events = (
                await session.execute(
                    select(AnalyticsEvent).order_by(AnalyticsEvent.timestamp.desc()).limit(20)
                )
            ).scalars().all()

            chat_sessions = await scalar_count(
                session,
                select(func.count(distinct(ChatMetric.session_id))).where(ChatMetric.timestamp >= week_start),
            )
            repeat_sessions = await scalar_count(
                session,
                select(func.count()).select_from(
                    select(ChatMetric.session_id)
                    .where(ChatMetric.timestamp >= week_start)
                    .group_by(ChatMetric.session_id)
                    .having(func.sum(ChatMetric.questions_count) > 1)
                    .subquery()
                ),
            )

        citation_values = [row.citation_coverage for row in rag_rows]
        avg_citation = sum(citation_values) / len(citation_values) if citation_values else 0.0
        avg_retrieval = sum(row.retrieval_latency for row in rag_rows) / len(rag_rows) if rag_rows else 0.0
        avg_generation = sum(row.generation_latency for row in rag_rows) / len(rag_rows) if rag_rows else 0.0
        avg_chunks = sum(row.chunks_retrieved for row in rag_rows) / len(rag_rows) if rag_rows else 0.0

        return AnalyticsDashboard(
            generated_at=now,
            overview=AnalyticsOverview(
                daily_active_users=dau,
                weekly_active_users=wau,
                questions_today=questions_today,
                videos_processed_today=videos_today,
                avg_session_time_ms=round(avg_session, 2),
                avg_processing_time_ms=round(avg_processing, 2),
                voice_usage_rate=rate(voice_completed, max(voice_started, total_searches)),
                search_success_rate=rate(completed_searches, total_searches),
            ),
            ai_metrics={
                "rag_latency": [
                    MetricPoint(label=fmt_time(row.timestamp), value=row.retrieval_latency + row.generation_latency)
                    for row in rag_rows[-30:]
                ],
                "token_usage": [
                    MetricPoint(label=fmt_time(row.timestamp), value=row.prompt_tokens + row.completion_tokens)
                    for row in rag_rows[-30:]
                ],
                "chunk_retrieval": [
                    MetricPoint(label=fmt_time(row.timestamp), value=row.chunks_retrieved)
                    for row in rag_rows[-30:]
                ],
                "citation_coverage": round(avg_citation, 2),
                "avg_retrieval_latency": round(avg_retrieval, 2),
                "avg_generation_latency": round(avg_generation, 2),
                "avg_chunks_retrieved": round(avg_chunks, 2),
            },
            pipeline_metrics={
                "transcript_extraction": [
                    MetricPoint(label=row.video_id[-6:], value=row.transcript_time) for row in video_rows[-20:]
                ],
                "embedding_duration": [
                    MetricPoint(label=row.video_id[-6:], value=row.embedding_time) for row in video_rows[-20:]
                ],
                "processing_duration": [
                    MetricPoint(label=row.video_id[-6:], value=row.processing_time) for row in video_rows[-20:]
                ],
                "chunk_count": [
                    MetricPoint(label=row.video_id[-6:], value=row.chunk_count) for row in video_rows[-20:]
                ],
            },
            ux_metrics={
                "carousel_click_rate": rate(awaited_count(events, "video_selected"), awaited_count(events, "carousel_scrolled")),
                "voice_failures": awaited_count(events, "voice_search_failed"),
                "chat_retention": rate(repeat_sessions, chat_sessions),
                "timestamp_clicks": awaited_count(events, "timestamp_clicked"),
                "chatbot_interactions": awaited_count(events, "3d_chatbot_interacted"),
            },
            business_metrics={
                "sessions": chat_sessions,
                "return_rate": rate(repeat_sessions, chat_sessions),
                "videos_processed": len(video_rows),
                "questions_per_day": round(questions_today, 2),
                "avg_processing_time": round(avg_processing, 2),
                "daily_activity": event_series(events),
            },
            recent_events=[
                {
                    "event_type": event.event_type,
                    "timestamp": event.timestamp.isoformat(),
                    "page": event.page,
                    "duration_ms": event.duration_ms,
                    "metadata_json": event.metadata_json,
                }
                for event in events
            ],
        )

    async def _write(self, row: object) -> None:
        if not self.config.analytics_enabled:
            return
        async with analytics_session() as session:
            session.add(row)
            await session.commit()


async def scalar_count(session, query) -> int:
    return int((await session.execute(query)).scalar_one() or 0)


async def scalar_float(session, query) -> float:
    return float((await session.execute(query)).scalar_one() or 0.0)


async def event_count(session, event_type: str, since: datetime) -> int:
    return await scalar_count(
        session,
        select(func.count(AnalyticsEvent.id)).where(
            AnalyticsEvent.event_type == event_type,
            AnalyticsEvent.timestamp >= since,
        ),
    )


def rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round((float(numerator) / float(denominator)) * 100, 2)


def fmt_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%m-%d %H:%M")


def awaited_count(events: list[AnalyticsEvent], event_type: str) -> int:
    return sum(1 for event in events if event.event_type == event_type)


def event_series(events: list[AnalyticsEvent]) -> list[MetricPoint]:
    buckets: dict[str, int] = {}
    for event in events:
        label = event.timestamp.strftime("%m-%d")
        buckets[label] = buckets.get(label, 0) + 1
    return [MetricPoint(label=label, value=value) for label, value in sorted(buckets.items())]


@lru_cache
def get_analytics_service() -> AnalyticsService:
    return AnalyticsService(settings)
