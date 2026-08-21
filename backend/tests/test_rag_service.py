import asyncio

import pytest
from fastapi import HTTPException
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy.exc import SQLAlchemyError

from app.analytics.schemas import ChatMetricCreate, RAGMetricCreate
from app.core.config import settings
from app.schemas.rag import ChatMessage
from app.schemas.vectorstore import VectorSearchResult
from app.services.conversation_store import InMemoryConversationStore
from app.services.rag_service import (
    SUMMARY_MAX_CHARS,
    RAGService,
    build_citations,
    format_context,
    format_memory,
    format_timestamp,
)


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
    # The summary branch must still go through the same side effects as the
    # retrieval path: a session assigned, and the exchange remembered.
    assert response.session_id
    memory_roles_and_content = [(m.role, m.content) for m in response.memory]
    assert ("user", "What is this video about?") in memory_roles_and_content
    assert any(
        role == "assistant" and "Overview" in content for role, content in memory_roles_and_content
    )
    user_index = memory_roles_and_content.index(("user", "What is this video about?"))
    assistant_index = next(
        i
        for i, (role, content) in enumerate(memory_roles_and_content)
        if role == "assistant" and "Overview" in content
    )
    assert user_index < assistant_index


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


def _chunk_for_transcript_length(target_length: int):
    """Build one chunk whose `rebuild_transcript([...])` output is exactly `target_length` chars.

    Derives the "[MM:SS] " prefix length from format_timestamp itself rather
    than hardcoding it, so a change to the timestamp format cannot silently
    desync these boundary tests the way a hardcoded prefix length would.
    """
    from app.schemas.chunks import TranscriptChunk

    prefix_length = len(f"[{format_timestamp(0.0)}] ")
    return TranscriptChunk(
        chunk_id="vid1-0", index=0, video_id="vid1", text="x" * (target_length - prefix_length),
        start_seconds=0.0, end_seconds=60.0, segment_indices=[0],
        token_estimate=5, metadata={"source": "captions", "language": "en"},
    )


async def test_summary_falls_back_when_the_transcript_is_just_over_the_limit(monkeypatch) -> None:  # noqa: ANN001
    # Boundary probe for summarize_video's `>` check: one character over
    # SUMMARY_MAX_CHARS, paired with the exactly-at-the-limit case below, is
    # what actually distinguishes `>` from a `>=` mix-up. A transcript that is
    # merely "much too long" (as a comfortably-over case would be) cannot -
    # both operators reject it identically.
    huge = [_chunk_for_transcript_length(SUMMARY_MAX_CHARS + 1)]
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(huge)
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    # The retrieval path ran instead of the summary - proven by the search
    # having happened.
    assert service.vectorstore.last_query == "What is this video about?"


async def test_summary_runs_when_the_transcript_is_exactly_at_the_limit(monkeypatch) -> None:  # noqa: ANN001
    # The other half of the boundary: exactly SUMMARY_MAX_CHARS must still be
    # summarised, not rejected. A `>=` mix-up would make this fall back to
    # retrieval instead, which the assertions below catch.
    exact = [_chunk_for_transcript_length(SUMMARY_MAX_CHARS)]
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(exact)
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    response = await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    # The summary path ran - no search happened, and the answer is the raw
    # model output rather than the retrieval-path's synthesized text.
    assert service.vectorstore.last_query is None
    assert response.answer == "a grounded answer"


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


class RaisingChunksVectorStoreService(CapturingVectorStoreService):
    """A store whose chunk listing is unreachable, like a connection-level outage."""

    async def list_video_chunks(self, video_id):  # noqa: ANN001
        raise OSError("connection refused")


async def test_summarize_video_returns_none_when_the_store_cannot_be_read() -> None:
    # Reachable in production whenever the vectorstore backend is down; must degrade
    # to retrieval like every other summarize_video failure, not raise.
    service = make_rag_service()
    service.vectorstore = RaisingChunksVectorStoreService()

    result = await service.summarize_video(message="What is this video about?", video_id="vid1")

    assert result is None


async def test_summarize_video_returns_none_when_the_model_answer_is_blank(monkeypatch) -> None:  # noqa: ANN001
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model", lambda streaming: FakeListChatModel(responses=["   "])
    )

    result = await service.summarize_video(message="What is this video about?", video_id="vid1")

    assert result is None


async def test_narrow_question_makes_exactly_one_model_call(monkeypatch) -> None:  # noqa: ANN001
    # The primary constraint of this feature: a narrow question must not pay for a
    # summarisation attempt that gets thrown away. An implementation that called
    # summarize_video unconditionally and discarded the result for narrow questions
    # would pass every other test in this file but fail this one.
    calls = {"count": 0}

    def counting_model(streaming):  # noqa: ANN001
        calls["count"] += 1
        return FakeListChatModel(responses=["a grounded answer"])

    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(service, "create_chat_model", counting_model)

    await service.answer(
        message="How do I do addition in Python?", video_id="vid1", session_id=None, top_k=5
    )

    assert calls["count"] == 1


# ---------------------------------------------------------------------------
# _record_rag_metrics: what actually gets sent to analytics
# ---------------------------------------------------------------------------


class RecordingAnalyticsService:
    """Captures every RAGMetricCreate/ChatMetricCreate instead of writing to a database.

    `safe_track` on the real AnalyticsService silently drops the awaitable when
    analytics is disabled (as it is in tests), so a double that stands in for
    `get_analytics_service()` itself - rather than trying to flip that setting -
    is the least invasive way to see what `_record_rag_metrics` actually built.
    """

    def __init__(self) -> None:
        self.rag_metrics: list[RAGMetricCreate] = []
        self.chat_metrics: list[ChatMetricCreate] = []

    async def track_rag_metric(self, metric: RAGMetricCreate) -> None:
        self.rag_metrics.append(metric)

    async def track_chat_metric(self, metric: ChatMetricCreate) -> None:
        self.chat_metrics.append(metric)

    async def safe_track(self, awaitable) -> None:  # noqa: ANN001
        await awaitable


async def test_summary_metrics_use_the_characters_to_tokens_ratio(monkeypatch) -> None:  # noqa: ANN001
    # The regression guard for the unit mix-up: context_chars is a character count,
    # so the token estimate must come from `// 4`, not the words-to-tokens `* 4 // 3`
    # used elsewhere in this file. Derived from the actual rebuilt transcript rather
    # than hardcoded, so a change to make_video_chunks() cannot silently desync it.
    from app.services.summary import rebuild_transcript

    chunks = make_video_chunks()
    transcript = rebuild_transcript(chunks)
    expected_tokens = max(1, len(transcript) // 4)
    wrong_tokens = max(1, len(transcript) * 4 // 3)
    assert expected_tokens != wrong_tokens  # otherwise this test could not tell them apart

    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(chunks)
    recorder = RecordingAnalyticsService()
    monkeypatch.setattr("app.services.rag_service.get_analytics_service", lambda: recorder)
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(
            responses=["Overview. [00:00] the start. [02:30] the end."]
        ),
    )

    await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    assert len(recorder.rag_metrics) == 1
    metric = recorder.rag_metrics[0]
    assert metric.context_tokens == expected_tokens
    assert metric.context_tokens != wrong_tokens
    # Citations were produced (both timestamps landed in a chunk), so coverage is full.
    assert metric.citation_coverage == 100.0
    # retrieved_context is deliberately empty on the summary path - see `answer`.
    assert metric.chunks_retrieved == 0


async def test_summary_metrics_zero_coverage_without_valid_timestamps(monkeypatch) -> None:  # noqa: ANN001
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    recorder = RecordingAnalyticsService()
    monkeypatch.setattr("app.services.rag_service.get_analytics_service", lambda: recorder)
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["An overview with no timestamps at all."]),
    )

    await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    assert len(recorder.rag_metrics) == 1
    metric = recorder.rag_metrics[0]
    assert metric.citation_coverage == 0.0
    assert metric.chunks_retrieved == 0


class SlowChunkListingVectorStoreService(ChunkListingVectorStoreService):
    """Adds a measurable delay to list_video_chunks.

    Without it, retrieval_ms could come back as a genuinely-tiny-but-nonzero
    float purely from perf_counter noise even with the old `retrieval_ms=0`
    bug, making a bare `> 0` assertion unreliable. Sleeping first makes the
    measured value large enough to be an unambiguous regression guard.
    """

    async def list_video_chunks(self, video_id):  # noqa: ANN001
        await asyncio.sleep(0.02)
        return await super().list_video_chunks(video_id)


async def test_summary_records_real_retrieval_latency_not_zero(monkeypatch) -> None:  # noqa: ANN001
    # Regression guard: the summary path used to pass retrieval_ms=0 to
    # _record_rag_metrics, which was untrue - list_video_chunks is a full
    # per-video table read - and skewed analytics' avg_retrieval_latency
    # toward zero on every summary click (the frontend's first suggested
    # prompt). generation_latency must not double-count that same read.
    service = make_rag_service()
    service.vectorstore = SlowChunkListingVectorStoreService(make_video_chunks())
    recorder = RecordingAnalyticsService()
    monkeypatch.setattr("app.services.rag_service.get_analytics_service", lambda: recorder)
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["Overview. [00:00] the start."]),
    )

    await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    assert len(recorder.rag_metrics) == 1
    metric = recorder.rag_metrics[0]
    # Threshold set well below the 0.02s (20ms) sleep, not at it: Windows'
    # asyncio.sleep can return a few ms early, so asserting close to the full
    # sleep duration is flaky. 10ms is still unambiguously distinguishable
    # from the old bug's hardcoded 0.
    assert metric.retrieval_latency >= 10.0
    assert metric.generation_latency >= 0.0


async def test_retrieval_metrics_context_tokens_unchanged_without_context_chars(monkeypatch) -> None:  # noqa: ANN001
    # The regression guard for the whole context_chars addition: when it is None
    # (the retrieval path), context_tokens must still come from retrieved_context
    # exactly as it did before context_chars existed.
    service = make_rag_service()
    recorder = RecordingAnalyticsService()
    monkeypatch.setattr("app.services.rag_service.get_analytics_service", lambda: recorder)
    monkeypatch.setattr(
        service, "create_chat_model", lambda streaming: FakeListChatModel(responses=["a grounded answer"])
    )

    await service.answer(
        message="How do I do addition in Python?", video_id="vid1", session_id=None, top_k=3
    )

    assert len(recorder.rag_metrics) == 1
    metric = recorder.rag_metrics[0]
    result = make_result()
    # FakeVectorStoreService returns one make_result(), whose metadata has no
    # "token_estimate", so this falls back to the words-to-tokens estimate.
    expected_tokens = max(1, len(result.text.split()) * 4 // 3)
    assert metric.context_tokens == expected_tokens


# ---------------------------------------------------------------------------
# Broad questions take the summarisation path in the streaming path too
# ---------------------------------------------------------------------------


async def test_stream_answer_emits_a_summary_as_one_token_event(monkeypatch) -> None:  # noqa: ANN001
    # The model call is not streamed, so pretending to stream it would only add
    # machinery. One token event, then done.
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["Overview. [00:00] the start."]),
    )

    events = [
        event
        async for event in service.stream_answer(
            message="What is this video about?", video_id="vid1", session_id=None, top_k=5
        )
    ]

    types = [e.type for e in events]
    assert types == ["context", "token", "done"]
    assert events[1].token == "Overview. [00:00] the start."
    assert events[-1].answer == "Overview. [00:00] the start."
    assert [c.chunk_id for c in events[-1].citations] == ["vid1-0"]
    assert events[0].retrieved_context == []


async def test_stream_answer_falls_back_to_retrieval_when_summarising_fails(monkeypatch) -> None:  # noqa: ANN001
    # FailingChatModel only overrides `_call`, the sync entry point LangChain's
    # `ainvoke` routes through by default. It does NOT override `_astream`, so
    # the inherited FakeListChatModel implementation is what the fallback's
    # `chain.astream(...)` actually runs, and it succeeds. That means this test
    # proves the search ran (via `last_query` below) - i.e. that the fallback
    # path was taken - not that generation itself failed; a model that failed
    # identically on both `ainvoke` and `astream` would make this test pass for
    # the wrong reason (or not at all, if both raised).
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FailingChatModel(responses=["unused"]),
    )

    events = [
        event
        async for event in service.stream_answer(
            message="What is this video about?", video_id="vid1", session_id=None, top_k=5
        )
    ]

    assert service.vectorstore.last_query == "What is this video about?"
    assert events[-1].type == "done"


class UnreachableStoreVectorStoreService:
    """A store whose database answers the connection and then refuses the query."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def similarity_search(self, query, limit=5, video_id=None):  # noqa: ANN001
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        SQLAlchemyError("server closed the connection unexpectedly"),
        OSError("connection refused"),
    ],
    ids=["database refused the query", "socket-level failure"],
)
async def test_retrieval_failure_becomes_a_502_that_names_the_cause(error) -> None:  # noqa: ANN001
    """Retrieval is the product, so it must fail loudly - and legibly.

    AGENTS.md has claimed since the conversation-memory work that retrieval
    "fails loudly with a 502", deliberately the opposite of memory, which
    degrades. That was true of `routes/vectorstore.py` and was never true here -
    `prepare_context` had no handling at all, so a store outage surfaced through
    `/api/chat` and `/api/agent/chat` as a bare 500. Those two are the endpoints
    the frontend uses; the route that had the good error message is not.

    Both error shapes are covered because the distinction is what broke in
    production on 2026-08-21: only the socket-level one is an OSError, and a
    paused Supabase project raises the other.
    """
    service = RAGService(
        config=settings,
        vectorstore=UnreachableStoreVectorStoreService(error),
        memory=InMemoryConversationStore(),
    )

    with pytest.raises(HTTPException) as excinfo:
        await service.prepare_context(
            message="what is a loop?", video_id="vid1", session_id=None, top_k=5
        )

    assert excinfo.value.status_code == 502
    detail = excinfo.value.detail.lower()
    assert "paused" in detail
    # Must reassure that data is not gone: the fear on seeing this is that the
    # ingested videos were lost, which would send someone re-ingesting for nothing.
    assert "not lost" in detail


async def test_a_paused_database_still_yields_502_even_though_memory_is_read_first() -> None:
    """The realistic outage: ONE database, so every store fails at once.

    prepare_context reads conversation history before it searches, so with a
    paused database `_get_history` raises first. If that read does not treat a
    Postgres-level error as an outage it escapes as a bare 500 and the 502 from
    retrieval never runs - the fix below it would be dead code in the only
    situation it was written for. Memory must degrade here (empty history) so
    that retrieval can be the thing that fails, loudly and legibly.
    """
    class UnreachableConversationStore:
        def create_session_id(self) -> str:
            return "session-1"

        async def get_messages(self, session_id):  # noqa: ANN001
            raise SQLAlchemyError("server closed the connection unexpectedly")

        async def append_exchange(self, session_id, user_message, assistant_message):  # noqa: ANN001
            raise SQLAlchemyError("server closed the connection unexpectedly")

    service = RAGService(
        config=settings,
        vectorstore=UnreachableStoreVectorStoreService(
            SQLAlchemyError("server closed the connection unexpectedly")
        ),
        memory=UnreachableConversationStore(),
    )

    with pytest.raises(HTTPException) as excinfo:
        await service.prepare_context(
            message="what is a loop?", video_id="vid1", session_id=None, top_k=5
        )

    assert excinfo.value.status_code == 502
    assert "paused" in excinfo.value.detail.lower()
