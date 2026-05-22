from fastapi.testclient import TestClient

from app.api.routes.vectorstore import get_chunking_service, get_vectorstore_service
from app.main import app
from app.schemas.chunks import TranscriptChunk
from app.schemas.transcript import TranscriptResponse, TranscriptSegment


class FakeChunkingService:
    async def chunk_transcript(self, transcript, options):  # noqa: ANN001
        return (
            [
                TranscriptChunk(
                    chunk_id=f"{transcript.video_id}:0:test",
                    index=0,
                    video_id=transcript.video_id,
                    text="Stored chunk.",
                    start_seconds=0.0,
                    end_seconds=5.0,
                    segment_indices=[0],
                    token_estimate=3,
                    metadata={
                        "video_id": transcript.video_id,
                        "source": transcript.source,
                        "language": transcript.language or "",
                        "chunk_index": 0,
                        "start_seconds": 0.0,
                        "end_seconds": 5.0,
                        "segment_indices": [0],
                    },
                    embedding=[0.1, 0.2, 0.3],
                )
            ],
            "text-embedding-3-small",
        )


class FakeVectorStoreService:
    async def upsert_chunks(self, chunks):  # noqa: ANN001
        return [chunk.chunk_id for chunk in chunks]


def test_ingest_transcript_chunks_route() -> None:
    app.dependency_overrides[get_chunking_service] = lambda: FakeChunkingService()
    app.dependency_overrides[get_vectorstore_service] = lambda: FakeVectorStoreService()
    client = TestClient(app)
    body = {
        "transcript": TranscriptResponse(
            video_id="video123",
            language="en",
            source="youtube_transcript_api",
            segment_count=1,
            full_text="Stored chunk.",
            segments=[
                TranscriptSegment(
                    index=0,
                    start_seconds=0.0,
                    end_seconds=5.0,
                    duration_seconds=5.0,
                    text="Stored chunk.",
                )
            ],
        ).model_dump(),
    }

    response = client.post("/api/vectorstore/transcripts", json=body)

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["video_id"] == "video123"
    assert payload["chunk_count"] == 1
    assert payload["stored_chunk_ids"] == ["video123:0:test"]
