from fastapi.testclient import TestClient

from app.api.routes.transcripts import get_transcript_service
from app.main import app
from app.schemas.transcript import TranscriptResponse, TranscriptSegment


class FakeTranscriptService:
    async def get_transcript(self, video_id, options):  # noqa: ANN001
        return TranscriptResponse(
            video_id=video_id,
            language=options.language,
            source="youtube_transcript_api",
            segment_count=1,
            full_text="Hello from transcript.",
            segments=[
                TranscriptSegment(
                    index=0,
                    start_seconds=0.0,
                    end_seconds=2.0,
                    duration_seconds=2.0,
                    text="Hello from transcript.",
                )
            ],
        )


def test_get_video_transcript_route() -> None:
    app.dependency_overrides[get_transcript_service] = lambda: FakeTranscriptService()
    client = TestClient(app)

    response = client.get("/api/videos/abc123xyz/transcript", params={"language": "en"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["video_id"] == "abc123xyz"
    assert payload["source"] == "youtube_transcript_api"
    assert payload["segments"][0]["start_seconds"] == 0.0
