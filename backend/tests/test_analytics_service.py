import pytest
from sqlalchemy import select

from app.analytics.models import AnalyticsEvent, ChatMetric, RAGMetric, VideoMetric
from app.analytics.schemas import (
    AnalyticsEventCreate,
    ChatMetricCreate,
    RAGMetricCreate,
    VideoMetricCreate,
)
from app.analytics.service import AnalyticsService, rate, event_series
from app.core.config import Settings


def make_service(enabled: bool = True) -> AnalyticsService:
    return AnalyticsService(Settings(analytics_enabled=enabled, analytics_database_url="sqlite+aiosqlite:///:memory:"))


# ── safe_track ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_safe_track_swallows_exceptions(patched_db):
    service = make_service()

    async def boom():
        raise RuntimeError("db exploded")

    await service.safe_track(boom())  # must not raise


@pytest.mark.asyncio
async def test_safe_track_noop_when_disabled(patched_db, test_engine):
    service = make_service(enabled=False)
    event = AnalyticsEventCreate(event_type="disabled_test")
    await service.safe_track(service.track_event(event))

    async with test_engine.connect() as conn:
        result = await conn.execute(select(AnalyticsEvent))
        assert result.fetchall() == []


# ── track_event ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_track_event_persists_row(patched_db, test_engine):
    service = make_service()
    await service.track_event(
        AnalyticsEventCreate(
            event_type="search_submitted",
            session_id="sess_abc",
            user_id="anon_xyz",
            page="/",
            duration_ms=120.5,
            metadata_json={"query": "python"},
        )
    )

    async with test_engine.connect() as conn:
        rows = (await conn.execute(select(AnalyticsEvent))).fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == "search_submitted"
    assert row.session_id == "sess_abc"
    assert row.duration_ms == pytest.approx(120.5)


@pytest.mark.asyncio
async def test_track_event_safe_persists_row(patched_db, test_engine):
    service = make_service()
    await service.track_event_safe(
        "voice_search_started",
        session_id="sess_1",
        metadata_json={"engine": "whisper"},
    )

    async with test_engine.connect() as conn:
        rows = (await conn.execute(select(AnalyticsEvent))).fetchall()

    assert len(rows) == 1
    assert rows[0].event_type == "voice_search_started"


# ── track_video_metric ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_track_video_metric_persists_row(patched_db, test_engine):
    service = make_service()
    await service.track_video_metric(
        VideoMetricCreate(
            video_id="abc123",
            processing_time=1500.0,
            transcript_time=800.0,
            embedding_time=700.0,
            chunk_count=42,
            whisper_used=True,
        )
    )

    async with test_engine.connect() as conn:
        rows = (await conn.execute(select(VideoMetric))).fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row.video_id == "abc123"
    assert row.chunk_count == 42
    assert row.whisper_used is True


# ── track_rag_metric ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_track_rag_metric_persists_row(patched_db, test_engine):
    service = make_service()
    await service.track_rag_metric(
        RAGMetricCreate(
            query="What is this video about?",
            retrieval_latency=120.0,
            generation_latency=800.0,
            chunks_retrieved=5,
            embedding_model="text-embedding-3-small",
            citation_coverage=80.0,
            context_tokens=400,
            prompt_tokens=450,
            completion_tokens=200,
            response_length=350,
            hallucination_warning=False,
        )
    )

    async with test_engine.connect() as conn:
        rows = (await conn.execute(select(RAGMetric))).fetchall()

    assert len(rows) == 1
    assert rows[0].chunks_retrieved == 5
    assert rows[0].citation_coverage == pytest.approx(80.0)


# ── track_chat_metric ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_track_chat_metric_persists_row(patched_db, test_engine):
    service = make_service()
    await service.track_chat_metric(
        ChatMetricCreate(
            session_id="sess_chat",
            questions_count=3,
            avg_response_time=950.0,
            tokens_used=1200,
            followup_questions=2,
        )
    )

    async with test_engine.connect() as conn:
        rows = (await conn.execute(select(ChatMetric))).fetchall()

    assert len(rows) == 1
    assert rows[0].session_id == "sess_chat"
    assert rows[0].questions_count == 3


# ── dashboard ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_returns_valid_structure(patched_db):
    service = make_service()
    dashboard = await service.dashboard()

    assert dashboard.overview.daily_active_users >= 0
    assert dashboard.overview.weekly_active_users >= 0
    assert isinstance(dashboard.ai_metrics, dict)
    assert isinstance(dashboard.pipeline_metrics, dict)
    assert isinstance(dashboard.ux_metrics, dict)
    assert isinstance(dashboard.business_metrics, dict)
    assert isinstance(dashboard.recent_events, list)


@pytest.mark.asyncio
async def test_dashboard_counts_events(patched_db):
    service = make_service()
    for i in range(3):
        await service.track_event(
            AnalyticsEventCreate(event_type="search_submitted", user_id=f"anon_{i}")
        )

    dashboard = await service.dashboard()
    assert dashboard.business_metrics["sessions"] >= 0
    assert len(dashboard.recent_events) == 3


@pytest.mark.asyncio
async def test_ux_metrics_use_full_window_not_recent_events(patched_db):
    """UX metrics must count all events in the analytics window, not just the
    latest 20 kept for the recent-events feed."""
    service = make_service()
    for _ in range(25):
        await service.track_event(AnalyticsEventCreate(event_type="timestamp_clicked"))
    for _ in range(4):
        await service.track_event(AnalyticsEventCreate(event_type="voice_search_failed"))

    dashboard = await service.dashboard()

    assert dashboard.ux_metrics["timestamp_clicks"] == 25
    assert dashboard.ux_metrics["voice_failures"] == 4
    assert len(dashboard.recent_events) == 20


# ── helper functions ──────────────────────────────────────────────────────────

def test_rate_normal():
    assert rate(1, 4) == pytest.approx(25.0)


def test_rate_zero_denominator():
    assert rate(5, 0) == 0.0


def test_rate_full():
    assert rate(10, 10) == pytest.approx(100.0)


def test_event_series_groups_by_date(patched_db):
    from datetime import datetime, timezone
    from app.analytics.models import AnalyticsEvent

    events = [
        AnalyticsEvent(event_type="e", timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        AnalyticsEvent(event_type="e", timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        AnalyticsEvent(event_type="e", timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc)),
    ]
    series = event_series(events)
    labels = [p.label for p in series]
    assert "01-01" in labels
    assert "01-02" in labels
    jan1 = next(p for p in series if p.label == "01-01")
    assert jan1.value == 2
