import pytest
from httpx import ASGITransport, AsyncClient

from app.analytics.service import AnalyticsService
from app.core.config import Settings
from app.main import create_app


def make_service(patched_db) -> AnalyticsService:
    return AnalyticsService(Settings(analytics_enabled=True, analytics_database_url="sqlite+aiosqlite:///:memory:"))


@pytest.fixture
def app(patched_db):
    application = create_app()
    service = make_service(patched_db)
    from app.analytics.service import get_analytics_service
    application.dependency_overrides[get_analytics_service] = lambda: service
    return application


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── POST /api/analytics/events ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_event_returns_accepted(client):
    response = await client.post(
        "/api/analytics/events",
        json={
            "event_type": "search_submitted",
            "session_id": "sess_test",
            "metadata_json": {"query": "machine learning"},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_post_event_minimal_payload(client):
    response = await client.post(
        "/api/analytics/events",
        json={"event_type": "page_view"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_post_event_rejects_empty_event_type(client):
    response = await client.post(
        "/api/analytics/events",
        json={"event_type": ""},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_event_rejects_missing_event_type(client):
    response = await client.post(
        "/api/analytics/events",
        json={"session_id": "sess_1"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_event_rejects_negative_duration(client):
    response = await client.post(
        "/api/analytics/events",
        json={"event_type": "bad_event", "duration_ms": -1},
    )
    assert response.status_code == 422


# ── GET /api/analytics/dashboard ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_dashboard_returns_valid_shape(client):
    response = await client.get("/api/analytics/dashboard")
    assert response.status_code == 200

    data = response.json()
    assert "overview" in data
    assert "ai_metrics" in data
    assert "pipeline_metrics" in data
    assert "ux_metrics" in data
    assert "business_metrics" in data
    assert "recent_events" in data
    assert "generated_at" in data


@pytest.mark.asyncio
async def test_get_dashboard_overview_fields(client):
    response = await client.get("/api/analytics/dashboard")
    overview = response.json()["overview"]

    assert "daily_active_users" in overview
    assert "weekly_active_users" in overview
    assert "questions_today" in overview
    assert "videos_processed_today" in overview
    assert "voice_usage_rate" in overview
    assert "search_success_rate" in overview


@pytest.mark.asyncio
async def test_post_then_dashboard_shows_event(client):
    await client.post(
        "/api/analytics/events",
        json={"event_type": "video_selected", "session_id": "sess_dash"},
    )
    response = await client.get("/api/analytics/dashboard")
    assert response.status_code == 200
    events = response.json()["recent_events"]
    assert any(e["event_type"] == "video_selected" for e in events)
