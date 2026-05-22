from fastapi.testclient import TestClient

from app.api.routes.search import get_youtube_service
from app.core.config import Settings
from app.main import app
from app.services.youtube_service import YouTubeService


def test_search_requires_youtube_api_key() -> None:
    app.dependency_overrides[get_youtube_service] = lambda: YouTubeService(
        Settings(youtube_api_key=None)
    )
    client = TestClient(app)

    try:
        response = client.get("/api/search", params={"q": "python tutorial"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "YOUTUBE_API_KEY is not configured."
