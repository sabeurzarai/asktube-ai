from fastapi.testclient import TestClient

from app.api.routes.chunks import get_transcript_service
from app.main import app
from app.schemas.transcript import TranscriptResponse, TranscriptSegment


class FakeTranscriptService:
    async def get_transcript(self, video_id, options):  # noqa: ANN001
        return TranscriptResponse(
            video_id=video_id,
            language=options.language,
            source="youtube_transcript_api",
            segment_count=2,
            full_text="First idea. Second idea.",
            segments=[
                TranscriptSegment(
                    index=0,
                    start_seconds=0.0,
                    end_seconds=5.0,
                    duration_seconds=5.0,
                    text="First idea.",
                ),
                TranscriptSegment(
                    index=1,
                    start_seconds=5.0,
                    end_seconds=10.0,
                    duration_seconds=5.0,
                    text="Second idea.",
                ),
            ],
        )


def test_chunk_video_transcript_route() -> None:
    app.dependency_overrides[get_transcript_service] = lambda: FakeTranscriptService()
    client = TestClient(app)

    response = client.get(
        "/api/videos/abc123xyz/chunks",
        params={"language": "en", "include_embeddings": "false"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["video_id"] == "abc123xyz"
    assert payload["chunk_count"] == 1
    assert payload["chunks"][0]["start_seconds"] == 0.0
    assert payload["chunks"][0]["end_seconds"] == 10.0
