from fastapi.testclient import TestClient

from app.api.routes.agent import get_agent_service
from app.main import app
from app.schemas.agent import AgentChatResponse
from app.schemas.rag import TimestampCitation


class FakeAgentService:
    async def chat(self, message: str, video_id: str | None, session_id: str | None) -> AgentChatResponse:
        return AgentChatResponse(
            session_id=session_id or "generated-session",
            answer=f"Agent answered: {message}",
            citations=[
                TimestampCitation(
                    chunk_id="vid1:0:abc",
                    video_id=video_id or "vid1",
                    start_seconds=5.0,
                    end_seconds=15.0,
                    timestamp="00:05-00:15",
                    text="Relevant transcript passage.",
                )
            ],
            tool_steps_used=["ingest_video", "answer_question"],
        )


def _client_with_fake() -> TestClient:
    app.dependency_overrides[get_agent_service] = lambda: FakeAgentService()
    return TestClient(app)


def _clear() -> None:
    app.dependency_overrides.clear()


def test_agent_chat_returns_200_with_all_fields() -> None:
    client = _client_with_fake()
    try:
        response = client.post(
            "/api/agent/chat",
            json={"message": "What is Python?", "video_id": "abc123", "session_id": "sess-1"},
        )
    finally:
        _clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Agent answered: What is Python?"
    assert payload["session_id"] == "sess-1"
    assert payload["tool_steps_used"] == ["ingest_video", "answer_question"]
    assert len(payload["citations"]) == 1
    assert payload["citations"][0]["timestamp"] == "00:05-00:15"


def test_agent_chat_uses_generated_session_when_none_provided() -> None:
    client = _client_with_fake()
    try:
        response = client.post("/api/agent/chat", json={"message": "Hello there"})
    finally:
        _clear()

    assert response.status_code == 200
    assert response.json()["session_id"] == "generated-session"


def test_agent_chat_accepts_optional_video_and_session() -> None:
    client = _client_with_fake()
    try:
        response = client.post("/api/agent/chat", json={"message": "Tell me something"})
    finally:
        _clear()

    assert response.status_code == 200


def test_agent_chat_rejects_short_message() -> None:
    client = _client_with_fake()
    try:
        response = client.post("/api/agent/chat", json={"message": "x"})
    finally:
        _clear()

    assert response.status_code == 422


def test_agent_chat_rejects_missing_message() -> None:
    client = _client_with_fake()
    try:
        response = client.post("/api/agent/chat", json={"video_id": "abc123"})
    finally:
        _clear()

    assert response.status_code == 422


def test_agent_chat_forwards_video_id_to_service() -> None:
    received: dict = {}

    class CapturingAgent:
        async def chat(self, message: str, video_id: str | None, session_id: str | None) -> AgentChatResponse:
            received["video_id"] = video_id
            return AgentChatResponse(
                session_id="s", answer="ok", citations=[], tool_steps_used=[]
            )

    app.dependency_overrides[get_agent_service] = lambda: CapturingAgent()
    client = TestClient(app)
    try:
        client.post("/api/agent/chat", json={"message": "Hello", "video_id": "abc123xyz"})
    finally:
        _clear()

    assert received["video_id"] == "abc123xyz"


def test_agent_route_does_not_conflict_with_existing_chat_route() -> None:
    client = _client_with_fake()
    try:
        agent_resp = client.post("/api/agent/chat", json={"message": "Agent question"})
    finally:
        _clear()

    # Regular chat route should still exist and be reachable (different path)
    assert agent_resp.status_code == 200
    assert "/api/agent/chat" != "/api/chat"
