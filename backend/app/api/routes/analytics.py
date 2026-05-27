from fastapi import APIRouter, Depends, Response

from app.analytics.prometheus import render_metrics
from app.analytics.schemas import AnalyticsAccepted, AnalyticsDashboard, AnalyticsEventCreate
from app.analytics.service import AnalyticsService, get_analytics_service

router = APIRouter()


@router.post("/analytics/events", response_model=AnalyticsAccepted)
async def capture_analytics_event(
    event: AnalyticsEventCreate,
    service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsAccepted:
    await service.track_event(event)
    return AnalyticsAccepted()


@router.get("/analytics/dashboard", response_model=AnalyticsDashboard)
async def get_analytics_dashboard(
    service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsDashboard:
    return await service.dashboard()


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    payload, media_type = render_metrics()
    return Response(content=payload, media_type=media_type)
