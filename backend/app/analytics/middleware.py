import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.analytics.prometheus import HTTP_REQUEST_DURATION, REQUEST_COUNT
from app.analytics.schemas import AnalyticsEventCreate
from app.analytics.service import get_analytics_service


class AnalyticsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        start = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            route = request.scope.get("route")
            path_template = getattr(route, "path", path)

            if path not in {"/metrics", "/health"}:
                REQUEST_COUNT.labels(request.method, path_template, str(status_code)).inc()
                HTTP_REQUEST_DURATION.labels(request.method, path_template).observe(elapsed_ms / 1000)
                get_analytics_service().safe_track_background(
                    get_analytics_service().track_event(
                        AnalyticsEventCreate(
                            event_type="http_request",
                            session_id=request.headers.get("x-asktube-session-id"),
                            user_id=request.headers.get("x-asktube-user-id"),
                            page=request.headers.get("referer"),
                            duration_ms=elapsed_ms,
                            metadata_json={
                                "method": request.method,
                                "path": path_template,
                                "status_code": status_code,
                            },
                        )
                    )
                )
