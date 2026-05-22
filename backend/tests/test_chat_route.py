from fastapi.testclient import TestClient

from app.api.routes.chat import get_rag_service
from app.main import app
from app.schemas.rag import RAGChatResponse, RAGStreamEvent, TimestampCitation
from app.schemas.vectorstore import VectorSearchResult


class FakeRAGService:
    async def answer(self, message, video_id, session_id, top_k):  # noqa: ANN001
        return RAGChatResponse(
            session_id=session_id or "generated-session",
            answer=f"Answered: {message}",
            citations=[
                TimestampCitation(
                    chunk_id="video123:0:test",
                    video_id=video_id or "video123",
                    start_seconds=10.0,
                    end_seconds=20.0,
                    timestamp="00:10-00:20",
                    text="Relevant transcript context.",
                )
            ],
            retrieved_context=[
                VectorSearchResult(
                    chunk_id="video123:0:test",
                    video_id=video_id or "video123",
                    text="Relevant transcript context.",
                    start_seconds=10.0,
                    end_seconds=20.0,
                    segment_indices=[0],
                    distance=0.1,
                    metadata={"source": "youtube_transcript_api"},
                )
            ],
            memory=[],
        )


def test_chat_route_returns_timestamped_answer() -> None:
    app.dependency_overrides[get_rag_service] = lambda: FakeRAGService()
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "message": "What is the key idea?",
            "video_id": "video123",
            "session_id": "session-1",
            "top_k": 3,
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "session-1"
    assert payload["citations"][0]["timestamp"] == "00:10-00:20"
    assert payload["retrieved_context"][0]["start_seconds"] == 10.0


class FakeStreamingRAGService:
    async def stream_answer(self, message, video_id, session_id, top_k):  # noqa: ANN001
        yield RAGStreamEvent(type="context", session_id=session_id or "generated-session")
        yield RAGStreamEvent(type="token", session_id=session_id or "generated-session", token="Hello")
        yield RAGStreamEvent(type="token", session_id=session_id or "generated-session", token=" world")
        yield RAGStreamEvent(
            type="done",
            session_id=session_id or "generated-session",
            answer=f"Hello world: {message}",
            citations=[
                TimestampCitation(
                    chunk_id="video123:0:test",
                    video_id=video_id or "video123",
                    start_seconds=10.0,
                    end_seconds=20.0,
                    timestamp="00:10-00:20",
                    text="Relevant transcript context.",
                )
            ],
            retrieved_context=[],
            memory=[],
        )


def test_chat_stream_websocket(monkeypatch) -> None:  # noqa: ANN001
    import app.api.routes.chat as chat_route

    monkeypatch.setattr(chat_route, "get_rag_service", lambda: FakeStreamingRAGService())
    client = TestClient(app)

    with client.websocket_connect("/api/chat/stream") as websocket:
        ready = websocket.receive_json()
        websocket.send_json(
            {
                "message": "Stream this",
                "video_id": "video123",
                "session_id": "session-1",
                "top_k": 3,
            }
        )
        context = websocket.receive_json()
        first_token = websocket.receive_json()
        second_token = websocket.receive_json()
        done = websocket.receive_json()

    assert ready["type"] == "ready"
    assert context["type"] == "context"
    assert first_token == {
        "type": "token",
        "session_id": "session-1",
        "token": "Hello",
        "answer": None,
        "citations": None,
        "retrieved_context": None,
        "memory": None,
        "error": None,
    }
    assert second_token["token"] == " world"
    assert done["type"] == "done"
    assert done["answer"] == "Hello world: Stream this"
    assert done["citations"][0]["timestamp"] == "00:10-00:20"


def test_chat_stream_websocket_validation_error() -> None:
    client = TestClient(app)

    with client.websocket_connect("/api/chat/stream") as websocket:
        ready = websocket.receive_json()
        websocket.send_json({"message": "x"})
        error = websocket.receive_json()

    assert ready["type"] == "ready"
    assert error["type"] == "error"
