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


# ---------------------------------------------------------------------------
# The rewrite reaches retrieval - and only retrieval
# ---------------------------------------------------------------------------


CAPTURED_PROMPTS: list[str] = []


class CapturingChatModel(FakeListChatModel):
    """Records every prompt it is invoked with.

    A module-level list rather than a class attribute on purpose: FakeListChatModel
    is a pydantic model, so an annotated class attribute would become a field.
    """

    def _call(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        CAPTURED_PROMPTS.append("\n".join(str(m.content) for m in messages))
        return super()._call(messages, stop=stop, run_manager=run_manager, **kwargs)


class CapturingVectorStoreService:
    """Records the query it was searched with."""

    def __init__(self) -> None:
        self.last_query: str | None = None

    async def similarity_search(self, query, limit, video_id):  # noqa: ANN001
        self.last_query = query
        return [make_result()]


async def seeded_memory() -> tuple[InMemoryConversationStore, str]:
    memory = InMemoryConversationStore()
    session_id = memory.create_session_id()
    await memory.append_exchange(session_id, "What is this video about?", "Getting started with Python.")
    return memory, session_id


async def test_search_receives_the_rewritten_query(monkeypatch) -> None:  # noqa: ANN001
    memory, session_id = await seeded_memory()
    service = make_rag_service(memory)
    service.vectorstore = CapturingVectorStoreService()
    # One model instance, so its responses are consumed in order: the rewrite call
    # takes the first, generation the second.
    model = FakeListChatModel(responses=["which code editor does the tutorial use", "a grounded answer"])
    monkeypatch.setattr(service, "create_chat_model", lambda streaming: model)

    await service.answer(
        message="And what does it use?", video_id="vid1", session_id=session_id, top_k=3
    )

    assert service.vectorstore.last_query == "which code editor does the tutorial use"


async def test_first_turn_is_searched_with_the_raw_question(monkeypatch) -> None:  # noqa: ANN001
    # The regression guard for the whole feature: with no history there is nothing to
    # resolve against, so a rewrite could only make a good query worse.
    service = make_rag_service()
    service.vectorstore = CapturingVectorStoreService()
    monkeypatch.setattr(
        service, "create_chat_model", lambda streaming: FakeListChatModel(responses=["a rewrite"])
    )

    await service.answer(
        message="How do I do addition in Python?", video_id="vid1", session_id=None, top_k=3
    )

    assert service.vectorstore.last_query == "How do I do addition in Python?"


async def test_generation_receives_the_original_question_not_the_rewrite(monkeypatch) -> None:  # noqa: ANN001
    """The rewrite is for retrieval only.

    Feeding it into generation would answer a question the user never asked - a
    rewrite is a guess about intent, not a statement of it. This test is what stops
    someone later "simplifying" the code by passing the rewrite straight through.
    """
    memory, session_id = await seeded_memory()
    service = make_rag_service(memory)
    service.vectorstore = CapturingVectorStoreService()
    CAPTURED_PROMPTS.clear()
    model = CapturingChatModel(responses=["which code editor does the tutorial use", "a grounded answer"])
    monkeypatch.setattr(service, "create_chat_model", lambda streaming: model)

    await service.answer(
        message="And what does it use?", video_id="vid1", session_id=session_id, top_k=3
    )

    # prompts[0] is the rewrite call, prompts[1] is generation.
    assert len(CAPTURED_PROMPTS) == 2
    generation_prompt = CAPTURED_PROMPTS[1]
    assert "And what does it use?" in generation_prompt
    assert "which code editor does the tutorial use" not in generation_prompt


# ---------------------------------------------------------------------------
# Broad questions take the summarisation path
# ---------------------------------------------------------------------------


class ChunkListingVectorStoreService(CapturingVectorStoreService):
    """A store that can also hand back a whole video."""

    def __init__(self, chunks) -> None:  # noqa: ANN001
        super().__init__()
        self._chunks = chunks

    async def list_video_chunks(self, video_id):  # noqa: ANN001
        return list(self._chunks)


def make_video_chunks() -> list:
    from app.schemas.chunks import TranscriptChunk

    return [
        TranscriptChunk(
            chunk_id=f"vid1-{i}", index=i, video_id="vid1",
            text=f"section {i} of the video", start_seconds=float(i * 60),
            end_seconds=float(i * 60 + 60), segment_indices=[i], token_estimate=5,
            metadata={"source": "captions", "language": "en"},
        )
        for i in range(3)
    ]


async def test_broad_question_is_answered_from_the_whole_transcript(monkeypatch) -> None:  # noqa: ANN001
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(
            responses=["Overview. [00:00] the start. [02:30] the end."]
        ),
    )

    response = await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    # The search was never used: a summary is not a retrieval answer.
    assert service.vectorstore.last_query is None
    assert "Overview" in response.answer
    # 00:00 lands in chunk 0 (0-60s), 02:30 in chunk 2 (120-180s). Deliberately
    # NOT 02:00, which is the boundary between chunks 1 and 2 and would encode
    # an arbitrary tie-break into the test.
    assert [c.chunk_id for c in response.citations] == ["vid1-0", "vid1-2"]
    assert response.retrieved_context == []


async def test_narrow_question_still_takes_the_retrieval_path(monkeypatch) -> None:  # noqa: ANN001
    # The constraint that matters most: nothing else changes.
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    await service.answer(
        message="How do I do addition in Python?", video_id="vid1", session_id=None, top_k=5
    )

    assert service.vectorstore.last_query == "How do I do addition in Python?"


async def test_summary_falls_back_to_retrieval_when_the_model_fails(monkeypatch) -> None:  # noqa: ANN001
    # Degrade, do not fail: a broken summary must still produce the answer the
    # user would have got before this feature existed.
    #
    # create_chat_model is called twice here - once for the (failing) summary
    # attempt, once for the retrieval-path generation that should follow it - so
    # a single always-failing model would make the fallback fail too and prove
    # nothing beyond the fact that summarize_video caught its own exception.
    # This counts calls so only the FIRST one fails, letting the fallback
    # generation actually succeed and produce a real answer to assert on.
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    calls = {"count": 0}

    def flaky_then_working_model(streaming):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            return FailingChatModel(responses=["unused"])
        return FakeListChatModel(responses=["a grounded answer"])

    monkeypatch.setattr(service, "create_chat_model", flaky_then_working_model)

    response = await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    # The retrieval path ran instead - proven by the search having happened.
    assert service.vectorstore.last_query == "What is this video about?"
    assert response.answer


async def test_summary_falls_back_when_the_video_has_no_chunks(monkeypatch) -> None:  # noqa: ANN001
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService([])
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    response = await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    assert service.vectorstore.last_query == "What is this video about?"
    assert response.answer


async def test_summary_falls_back_when_the_transcript_is_too_long(monkeypatch) -> None:  # noqa: ANN001
    from app.schemas.chunks import TranscriptChunk

    huge = [
        TranscriptChunk(
            chunk_id="vid1-0", index=0, video_id="vid1", text="x" * 41_000,
            start_seconds=0.0, end_seconds=60.0, segment_indices=[0],
            token_estimate=5, metadata={"source": "captions", "language": "en"},
        )
    ]
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(huge)
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    assert service.vectorstore.last_query == "What is this video about?"


async def test_broad_question_without_a_video_takes_the_retrieval_path(monkeypatch) -> None:  # noqa: ANN001
    # There is nothing to summarise when no video is named.
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    await service.answer(
        message="What is this video about?", video_id=None, session_id=None, top_k=5
    )

    assert service.vectorstore.last_query == "What is this video about?"
