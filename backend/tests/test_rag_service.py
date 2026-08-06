from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core.config import settings
from app.schemas.rag import ChatMessage
from app.schemas.vectorstore import VectorSearchResult
from app.services.conversation_store import InMemoryConversationStore
from app.services.rag_service import RAGService, build_citations, format_context, format_memory, format_timestamp


def make_result(chunk_id: str = "video123:0:test") -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk_id,
        video_id="video123",
        text="The transcript says retrieval should happen before generation.",
        start_seconds=63.0,
        end_seconds=92.0,
        segment_indices=[2, 3],
        distance=0.12,
        metadata={"source": "youtube_transcript_api"},
    )


def test_format_timestamp() -> None:
    assert format_timestamp(5) == "00:05"
    assert format_timestamp(125) == "02:05"
    assert format_timestamp(3723) == "01:02:03"


def test_format_context_injects_timestamps_and_chunk_ids() -> None:
    context = format_context([make_result()])

    assert "01:03-01:32" in context
    assert "chunk_id=video123:0:test" in context
    assert "retrieval should happen before generation" in context


def test_build_citations_deduplicates_chunks() -> None:
    citations = build_citations([make_result(), make_result()])

    assert len(citations) == 1
    assert citations[0].timestamp == "01:03-01:32"
    assert citations[0].start_seconds == 63.0


async def test_conversation_memory_keeps_recent_exchange() -> None:
    memory = InMemoryConversationStore(max_messages=2)
    session_id = "session-1"

    await memory.append_exchange(session_id, "Question one", "Answer one")
    await memory.append_exchange(session_id, "Question two", "Answer two")

    messages = await memory.get_messages(session_id)
    assert messages == [
        ChatMessage(role="user", content="Question two"),
        ChatMessage(role="assistant", content="Answer two"),
    ]
    assert "Question two" in format_memory(messages)


# ---------------------------------------------------------------------------
# Degrade-rather-than-fail: conversation store down
# ---------------------------------------------------------------------------


class FakeVectorStoreService:
    async def similarity_search(self, query, limit, video_id):  # noqa: ANN001
        return [make_result()]


class FailingConversationStore:
    """Every database operation fails at the connection level."""

    def create_session_id(self) -> str:
        return "session-under-test"

    async def get_messages(self, session_id):  # noqa: ANN001
        raise OSError("connection refused")

    async def append_exchange(self, session_id, user_message, assistant_message):  # noqa: ANN001
        raise OSError("connection refused")


def make_rag_service(memory=None) -> RAGService:  # noqa: ANN001
    return RAGService(
        config=settings,
        vectorstore=FakeVectorStoreService(),
        memory=memory if memory is not None else InMemoryConversationStore(),
    )


async def test_answer_survives_a_conversation_store_that_cannot_be_read(monkeypatch) -> None:  # noqa: ANN001
    # Memory is an enhancement, not the product. Losing follow-up context is a mild
    # regression; refusing to answer is an outage.
    service = make_rag_service(memory=FailingConversationStore())
    monkeypatch.setattr(
        service, "create_chat_model", lambda streaming: FakeListChatModel(responses=["a grounded answer"])
    )

    response = await service.answer(
        message="what is this about", video_id="vid1", session_id=None, top_k=3
    )

    assert response.answer
    assert response.memory == []


async def test_answer_is_returned_even_when_it_cannot_be_stored(monkeypatch) -> None:  # noqa: ANN001
    # The expensive part - retrieval plus generation - already succeeded. Discarding
    # it because the history write failed would waste it for nothing.
    service = make_rag_service(memory=FailingConversationStore())
    monkeypatch.setattr(
        service, "create_chat_model", lambda streaming: FakeListChatModel(responses=["a grounded answer"])
    )

    response = await service.answer(
        message="what is this about", video_id="vid1", session_id=None, top_k=3
    )

    assert response.answer


async def test_stream_answer_survives_a_conversation_store_that_is_down(monkeypatch) -> None:  # noqa: ANN001
    # The streaming path reads memory before the first event and appends after the
    # last token; both must degrade the same way as the non-streaming path.
    service = make_rag_service(memory=FailingConversationStore())
    monkeypatch.setattr(
        service, "create_chat_model", lambda streaming: FakeListChatModel(responses=["a grounded answer"])
    )

    events = [
        event
        async for event in service.stream_answer(
            message="what is this about", video_id="vid1", session_id=None, top_k=3
        )
    ]

    context_event = events[0]
    done_event = events[-1]
    assert context_event.type == "context"
    assert context_event.memory == []
    assert done_event.type == "done"
    assert done_event.answer
    assert done_event.memory == []


# ---------------------------------------------------------------------------
# Query contextualization: rewriting a follow-up into a standalone search query
# ---------------------------------------------------------------------------


class FailingChatModel(FakeListChatModel):
    """A chat model whose provider is unreachable."""

    def _call(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        raise RuntimeError("provider is unavailable")


def some_history() -> list[ChatMessage]:
    return [
        ChatMessage(role="user", content="What is this video about?"),
        ChatMessage(role="assistant", content="Getting started with Python."),
    ]


async def test_contextualize_returns_the_message_unchanged_without_history() -> None:
    # First turns must cost nothing extra and must not be degraded by a rewrite.
    service = make_rag_service()

    assert await service._contextualize("How do I do addition?", []) == "How do I do addition?"


async def test_contextualize_makes_no_model_call_without_history(monkeypatch) -> None:  # noqa: ANN001
    # Counted rather than asserted inside the fake on purpose: _contextualize catches
    # broadly, so an AssertionError raised in there would be swallowed and this test
    # would pass without proving anything.
    calls = {"count": 0}

    def counting_model(streaming):  # noqa: ANN001
        calls["count"] += 1
        return FakeListChatModel(responses=["unused"])

    service = make_rag_service()
    monkeypatch.setattr(service, "create_chat_model", counting_model)

    await service._contextualize("How do I do addition?", [])

    assert calls["count"] == 0


async def test_contextualize_rewrites_using_history(monkeypatch) -> None:  # noqa: ANN001
    service = make_rag_service()
    monkeypatch.setattr(
        service,
        "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["which code editor does the tutorial use"]),
    )

    rewritten = await service._contextualize("And what does it use?", some_history())

    assert rewritten == "which code editor does the tutorial use"


async def test_contextualize_falls_back_to_the_original_when_the_model_fails(monkeypatch) -> None:  # noqa: ANN001
    # An enhancement must not be able to prevent an answer: a failed rewrite degrades
    # retrieval to exactly today's behaviour rather than raising.
    service = make_rag_service()
    monkeypatch.setattr(
        service, "create_chat_model", lambda streaming: FailingChatModel(responses=["unused"])
    )

    assert await service._contextualize("and the next one?", some_history()) == "and the next one?"


async def test_contextualize_falls_back_when_the_model_returns_blank(monkeypatch) -> None:  # noqa: ANN001
    service = make_rag_service()
    monkeypatch.setattr(
        service, "create_chat_model", lambda streaming: FakeListChatModel(responses=["   "])
    )

    assert await service._contextualize("and the next one?", some_history()) == "and the next one?"
