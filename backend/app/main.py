from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.services.observability_service import configure_langsmith


def create_app() -> FastAPI:
    configure_langsmith(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="FastAPI backend for AskTube AI.",
    )

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

    app.include_router(api_router, prefix="/api")

    return app


app = create_app()
