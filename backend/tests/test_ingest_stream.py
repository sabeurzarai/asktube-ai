from fastapi.testclient import TestClient

from app.api.routes.vectorstore import (
    get_chunking_service,
    get_transcript_service,
    get_vectorstore_service,
)
from app.main import app
from app.schemas.chunks import TranscriptChunk
from app.schemas.transcript import TranscriptResponse, TranscriptSegment


# ---------------------------------------------------------------------------
# Fake services
# ---------------------------------------------------------------------------

def _make_transcript() -> TranscriptResponse:
    return TranscriptResponse(
        video_id="abc123xy",
        language="en",
        source="youtube_transcript_api",
        segment_count=2,
        full_text="Hello world. This is a test.",
        segments=[
            TranscriptSegment(index=0, start_seconds=0.0, end_seconds=5.0, duration_seconds=5.0, text="Hello world."),
            TranscriptSegment(index=1, start_seconds=5.0, end_seconds=10.0, duration_seconds=5.0, text="This is a test."),
        ],
    )


def _make_chunk() -> TranscriptChunk:
    return TranscriptChunk(
        chunk_id="abc123xy:0:deadbeef0000",
        index=0,
        video_id="abc123xy",
        text="Hello world. This is a test.",
        start_seconds=0.0,
        end_seconds=10.0,
        segment_indices=[0, 1],
        token_estimate=7,
        metadata={
            "video_id": "abc123xy",
            "source": "youtube_transcript_api",
            "language": "en",
            "chunk_index": 0,
            "start_seconds": 0.0,
            "end_seconds": 10.0,
            "segment_indices": [0, 1],
        },
    )


class FakeTranscriptService:
    async def get_transcript(self, video_id, options):  # noqa: ANN001
        return _make_transcript()


class FakeChunkingService:
    async def chunk_transcript(self, transcript, options):  # noqa: ANN001
        return [_make_chunk()], None


class FakeVectorStoreService:
    async def upsert_chunks(self, chunks):  # noqa: ANN001
        return [c.chunk_id for c in chunks]


class FakeFailingTranscriptService:
    async def get_transcript(self, video_id, options):  # noqa: ANN001
        raise RuntimeError("No transcript available")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _override(transcript=None, chunking=None, vectorstore=None) -> None:
    if transcript:
        app.dependency_overrides[get_transcript_service] = lambda: transcript
    if chunking:
        app.dependency_overrides[get_chunking_service] = lambda: chunking
    if vectorstore:
        app.dependency_overrides[get_vectorstore_service] = lambda: vectorstore


def _clear() -> None:
    app.dependency_overrides.clear()


def _collect_events(ws) -> list[dict]:  # noqa: ANN001
    events = []
    while True:
        data = ws.receive_json()
        events.append(data)
        if data["type"] in ("ready", "error"):
            break
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ingest_stream_sends_step_events_then_ready() -> None:
    _override(
        transcript=FakeTranscriptService(),
        chunking=FakeChunkingService(),
        vectorstore=FakeVectorStoreService(),
    )
    client = TestClient(app)
    try:
        with client.websocket_connect("/api/videos/abc123xy/ingest/stream") as ws:
            events = _collect_events(ws)
    finally:
        _clear()

    step_types = [e["type"] for e in events]
    assert "step" in step_types
    assert events[-1]["type"] == "ready"
    assert events[-1]["progress"] == 100
    assert events[-1]["chunk_count"] == 1


def test_ingest_stream_step_sequence_has_transcript_and_chunking() -> None:
    _override(
        transcript=FakeTranscriptService(),
        chunking=FakeChunkingService(),
        vectorstore=FakeVectorStoreService(),
    )
    client = TestClient(app)
    try:
        with client.websocket_connect("/api/videos/abc123xy/ingest/stream") as ws:
            events = _collect_events(ws)
    finally:
        _clear()

    step_names = [e.get("step") for e in events]
    assert "transcript" in step_names
    assert "chunking" in step_names
    assert "embeddings" in step_names
    assert "ready" in step_names


def test_ingest_stream_progress_increases_monotonically() -> None:
    _override(
        transcript=FakeTranscriptService(),
        chunking=FakeChunkingService(),
        vectorstore=FakeVectorStoreService(),
    )
    client = TestClient(app)
    try:
        with client.websocket_connect("/api/videos/abc123xy/ingest/stream") as ws:
            events = _collect_events(ws)
    finally:
        _clear()

    progress_values = [e["progress"] for e in events]
    assert progress_values == sorted(progress_values), "Progress must only increase"
    assert progress_values[-1] == 100


def test_ingest_stream_sends_error_event_on_transcript_failure() -> None:
    _override(
        transcript=FakeFailingTranscriptService(),
        chunking=FakeChunkingService(),
        vectorstore=FakeVectorStoreService(),
    )
    client = TestClient(app)
    try:
        with client.websocket_connect("/api/videos/abc123xy/ingest/stream") as ws:
            events = _collect_events(ws)
    finally:
        _clear()

    assert events[-1]["type"] == "error"
    assert "error" in events[-1]
    assert "No transcript available" in events[-1]["error"]


def test_ingest_stream_each_event_has_required_fields() -> None:
    _override(
        transcript=FakeTranscriptService(),
        chunking=FakeChunkingService(),
        vectorstore=FakeVectorStoreService(),
    )
    client = TestClient(app)
    try:
        with client.websocket_connect("/api/videos/abc123xy/ingest/stream") as ws:
            events = _collect_events(ws)
    finally:
        _clear()

    for event in events:
        assert "type" in event
        assert "step" in event
        assert "label" in event
        assert "progress" in event
        assert isinstance(event["progress"], int)
