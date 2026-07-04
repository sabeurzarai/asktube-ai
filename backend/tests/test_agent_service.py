import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, ToolMessage

from app.core.config import Settings
from app.schemas.agent import AgentChatResponse
from app.schemas.rag import TimestampCitation
from app.schemas.vectorstore import VectorSearchResult
from app.services.agent_service import AgentService, _format_for_context
from app.services.memory_service import ConversationMemoryService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_settings() -> Settings:
    return Settings(
        openai_api_key="sk-test",
        youtube_api_key="yt-test",
    )


def make_memory() -> ConversationMemoryService:
    return ConversationMemoryService(max_messages=8)


def make_tool(name: str, return_value: dict) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.ainvoke = AsyncMock(return_value=return_value)
    return tool


def make_rag_tool_result() -> dict:
    return {
        "session_id": "session-abc",
        "answer": "Python is used for data science and web development.",
        "citations": [
            {
                "chunk_id": "vid1:0:abc",
                "video_id": "vid1",
                "start_seconds": 10.0,
                "end_seconds": 20.0,
                "timestamp": "00:10-00:20",
                "text": "Python is used for data science.",
            }
        ],
        "retrieved_context": [],
        "memory": [],
    }


def make_ai_message_with_tool_call(tool_name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args, "id": call_id}],
    )


def _make_bound_model(*responses: AIMessage) -> MagicMock:
    bound = MagicMock()
    bound.ainvoke = AsyncMock(side_effect=list(responses))
    return bound


# ---------------------------------------------------------------------------
# Tests - tool step tracking
# ---------------------------------------------------------------------------

def test_agent_records_tool_steps_used() -> None:
    memory = make_memory()
    answer_tool = make_tool("answer_question", make_rag_tool_result())
    service = AgentService(config=make_settings(), tools=[answer_tool], memory=memory)

    bound = _make_bound_model(
        make_ai_message_with_tool_call(
            "answer_question",
            {"message": "What is Python?", "video_id": "vid1", "session_id": None, "top_k": 5},
        ),
        AIMessage(content="Done"),
    )

    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        result = asyncio.run(service.chat("What is Python?", video_id="vid1", session_id=None))

    assert "answer_question" in result.tool_steps_used


def test_agent_records_multiple_tool_steps_in_order() -> None:
    memory = make_memory()
    ingest_tool = make_tool("ingest_video", {"video_id": "vid1", "chunk_count": 10, "status": "ingested"})
    answer_tool = make_tool("answer_question", make_rag_tool_result())
    service = AgentService(config=make_settings(), tools=[ingest_tool, answer_tool], memory=memory)

    bound = _make_bound_model(
        AIMessage(
            content="",
            tool_calls=[
                {"name": "ingest_video", "args": {"video_id": "vid1"}, "id": "call_1"},
            ],
        ),
        make_ai_message_with_tool_call(
            "answer_question",
            {"message": "What is Python?", "video_id": "vid1", "session_id": None, "top_k": 5},
            call_id="call_2",
        ),
        AIMessage(content="Done"),
    )

    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        result = asyncio.run(service.chat("What is Python?", video_id="vid1", session_id=None))

    assert result.tool_steps_used == ["ingest_video", "answer_question"]


# ---------------------------------------------------------------------------
# Tests - citations and answer extraction
# ---------------------------------------------------------------------------

def test_agent_extracts_citations_from_answer_question_result() -> None:
    memory = make_memory()
    answer_tool = make_tool("answer_question", make_rag_tool_result())
    service = AgentService(config=make_settings(), tools=[answer_tool], memory=memory)

    bound = _make_bound_model(
        make_ai_message_with_tool_call(
            "answer_question",
            {"message": "What is Python?", "video_id": "vid1", "session_id": None, "top_k": 5},
        ),
        AIMessage(content="Done"),
    )

    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        result = asyncio.run(service.chat("What is Python?", video_id="vid1", session_id=None))

    assert len(result.citations) == 1
    assert result.citations[0].timestamp == "00:10-00:20"
    assert result.citations[0].video_id == "vid1"


def test_agent_returns_answer_from_answer_question_tool() -> None:
    memory = make_memory()
    answer_tool = make_tool("answer_question", make_rag_tool_result())
    service = AgentService(config=make_settings(), tools=[answer_tool], memory=memory)

    bound = _make_bound_model(
        make_ai_message_with_tool_call(
            "answer_question",
            {"message": "What is Python?", "video_id": "vid1", "session_id": None, "top_k": 5},
        ),
        AIMessage(content="Done"),
    )

    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        result = asyncio.run(service.chat("What is Python?", video_id="vid1", session_id=None))

    assert result.answer == "Python is used for data science and web development."


def test_agent_falls_back_to_ai_message_content_when_no_answer_question() -> None:
    memory = make_memory()
    search_tool = make_tool("search_youtube_videos", {"query": "python", "count": 1, "videos": []})
    service = AgentService(config=make_settings(), tools=[search_tool], memory=memory)

    bound = _make_bound_model(
        make_ai_message_with_tool_call("search_youtube_videos", {"query": "python", "max_results": 5}),
        AIMessage(content="Here are some results for you."),
    )

    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        result = asyncio.run(service.chat("Find Python videos", video_id=None, session_id=None))

    assert result.answer == "Here are some results for you."
    assert result.citations == []


# ---------------------------------------------------------------------------
# Tests - memory management
# ---------------------------------------------------------------------------

def test_agent_appends_memory_when_answer_question_not_called() -> None:
    memory = make_memory()
    search_tool = make_tool("search_youtube_videos", {"query": "python", "count": 0, "videos": []})
    service = AgentService(config=make_settings(), tools=[search_tool], memory=memory)

    bound = _make_bound_model(
        make_ai_message_with_tool_call("search_youtube_videos", {"query": "python", "max_results": 10}),
        AIMessage(content="No videos found."),
    )

    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        result = asyncio.run(service.chat("Find python tutorials", video_id=None, session_id=None))

    messages = memory.get_messages(result.session_id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Find python tutorials"
    assert messages[1].role == "assistant"


def test_agent_does_not_double_append_memory_when_answer_question_called() -> None:
    memory = make_memory()
    answer_tool = make_tool("answer_question", make_rag_tool_result())
    service = AgentService(config=make_settings(), tools=[answer_tool], memory=memory)

    # Pre-seed memory as RAGService would (simulating answer_question appending internally)
    session_id = memory.create_session_id()
    bound = _make_bound_model(
        make_ai_message_with_tool_call(
            "answer_question",
            {"message": "What is Python?", "video_id": "vid1", "session_id": session_id, "top_k": 5},
        ),
        AIMessage(content="Done"),
    )

    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        asyncio.run(service.chat("What is Python?", video_id="vid1", session_id=session_id))

    # RAGService (mocked answer_tool) does not actually call memory.append_exchange,
    # so memory should remain empty - AgentService correctly skips the append.
    messages = memory.get_messages(session_id)
    assert len(messages) == 0


def test_agent_includes_prior_memory_in_context() -> None:
    memory = make_memory()
    session_id = memory.create_session_id()
    memory.append_exchange(session_id, "Previous question", "Previous answer")

    answer_tool = make_tool("answer_question", make_rag_tool_result())
    service = AgentService(config=make_settings(), tools=[answer_tool], memory=memory)

    captured_messages: list = []

    async def capture_ainvoke(messages: list) -> AIMessage:
        captured_messages.extend(messages)
        return AIMessage(content="Follow-up answer")

    bound = MagicMock()
    bound.ainvoke = AsyncMock(side_effect=capture_ainvoke)

    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        asyncio.run(service.chat("Follow-up question", video_id=None, session_id=session_id))

    # System + HumanMessage(prev) + AIMessage(prev) + HumanMessage(new)
    content_values = [m.content for m in captured_messages]
    assert "Previous question" in content_values
    assert "Previous answer" in content_values
    assert "Follow-up question" in content_values


# ---------------------------------------------------------------------------
# Tests - response schema
# ---------------------------------------------------------------------------

def test_agent_returns_session_id() -> None:
    memory = make_memory()
    service = AgentService(config=make_settings(), tools=[], memory=memory)

    bound = _make_bound_model(AIMessage(content="Hello"))
    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        result = asyncio.run(service.chat("Hi", video_id=None, session_id=None))

    assert isinstance(result.session_id, str)
    assert len(result.session_id) > 0


def test_agent_reuses_provided_session_id() -> None:
    memory = make_memory()
    service = AgentService(config=make_settings(), tools=[], memory=memory)

    bound = _make_bound_model(AIMessage(content="Hello"))
    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        mock_cls.return_value.bind_tools.return_value = bound
        result = asyncio.run(service.chat("Hi", video_id=None, session_id="my-session-123"))

    assert result.session_id == "my-session-123"


def test_agent_raises_503_without_api_key() -> None:
    from fastapi import HTTPException

    config = Settings(openai_api_key=None)  # force no key, overrides .env
    service = AgentService(config=config, tools=[], memory=make_memory())

    try:
        asyncio.run(service.chat("test", video_id=None, session_id=None))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 503


# ---------------------------------------------------------------------------
# Tests - _format_for_context helper
# ---------------------------------------------------------------------------

def test_format_for_context_search_returns_compact_video_list() -> None:
    result = {
        "count": 2,
        "videos": [
            {"video_id": "abc", "title": "Python Tutorial", "channel_title": "Mosh", "description": "long..."},
            {"video_id": "def", "title": "Python Advanced", "channel_title": "Mosh", "description": "long..."},
        ],
    }
    output = json.loads(_format_for_context("search_youtube_videos", result))
    assert output["count"] == 2
    assert all("description" not in v for v in output["videos"])


def test_format_for_context_ingest_returns_summary() -> None:
    result = {"video_id": "abc", "chunk_count": 45, "embedding_model": "text-embedding-3-small", "status": "ingested"}
    output = json.loads(_format_for_context("ingest_video", result))
    assert output["chunk_count"] == 45
    assert output["status"] == "ingested"


def test_format_for_context_answer_question_returns_answer_and_count() -> None:
    result = make_rag_tool_result()
    output = json.loads(_format_for_context("answer_question", result))
    assert "answer" in output
    assert output["citation_count"] == 1


# ---------------------------------------------------------------------------
# Tests - NVIDIA provider with tool-calling disabled (RAG fallback)
# ---------------------------------------------------------------------------

def test_nvidia_tool_calling_disabled_falls_back_to_rag_without_bind_tools() -> None:
    """NVIDIA_TOOL_CALLING=False → agent delegates to RAG; no bind_tools call.

    This exercises the provider opt-out path: the agent must NOT build the
    tool-calling pipeline. Instead it returns the RAG answer with its
    citations and an empty tool_steps_used list.
    """
    from app.schemas.rag import RAGChatResponse

    nvidia_config = Settings(
        openai_api_key="sk-test",
        llm_provider="nvidia",
        nvidia_api_key="nvapi-test",
        nvidia_tool_calling=False,
    )

    # Fake RAG service whose answer() returns a grounded response w/ citations.
    rag_service = MagicMock()
    rag_service.answer = AsyncMock(
        return_value=RAGChatResponse(
            session_id="rag-session-1",
            answer="Python is used for data science.",
            citations=[
                TimestampCitation(
                    chunk_id="vid1:0:abc",
                    video_id="vid1",
                    start_seconds=10.0,
                    end_seconds=20.0,
                    timestamp="00:10-00:20",
                    text="Python is used for data science.",
                )
            ],
            retrieved_context=[],
            memory=[],
        )
    )

    service = AgentService(
        config=nvidia_config,
        tools=[make_tool("answer_question", make_rag_tool_result())],
        memory=make_memory(),
        rag_service=rag_service,
    )

    with patch("app.services.llm_provider.ChatOpenAI") as mock_cls:
        result = asyncio.run(service.chat("What is Python?", video_id="vid1", session_id=None))

    # The agent must NOT have constructed a tool-calling model.
    mock_cls.return_value.bind_tools.assert_not_called()

    # The RAG answer and citations flow through, with no tool steps.
    assert result.answer == "Python is used for data science."
    assert len(result.citations) == 1
    assert result.citations[0].timestamp == "00:10-00:20"
    assert result.tool_steps_used == []
    assert result.session_id == "rag-session-1"
    # And the RAG service was actually consulted.
    rag_service.answer.assert_awaited_once()


def test_nvidia_without_api_key_raises_503() -> None:
    from fastapi import HTTPException

    config = Settings(
        openai_api_key="sk-test",  # embeddings still need OpenAI
        llm_provider="nvidia",
        nvidia_api_key=None,
    )
    service = AgentService(config=config, tools=[], memory=make_memory())

    try:
        asyncio.run(service.chat("test", video_id=None, session_id=None))
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 503
        assert "NVIDIA_API_KEY" in exc.detail
