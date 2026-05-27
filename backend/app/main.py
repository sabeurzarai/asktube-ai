from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.analytics.database import init_analytics_db
from app.analytics.middleware import AnalyticsMiddleware
from app.analytics.prometheus import render_metrics
from app.core.config import settings
from app.services.observability_service import configure_langsmith

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.analytics_enabled:
        try:
            await init_analytics_db()
        except Exception as exc:
            logger.warning("Analytics database initialization failed: %s", exc)
    yield


def create_app() -> FastAPI:
    configure_langsmith(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="FastAPI backend for AskTube AI.",
        lifespan=lifespan,
    )

    if settings.analytics_enabled:
        app.add_middleware(AnalyticsMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        payload, media_type = render_metrics()
        return Response(content=payload, media_type=media_type)

    app.include_router(api_router, prefix="/api")

    return app


app = create_app()
