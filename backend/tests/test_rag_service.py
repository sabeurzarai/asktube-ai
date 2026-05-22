from app.schemas.rag import ChatMessage
from app.schemas.vectorstore import VectorSearchResult
from app.services.memory_service import ConversationMemoryService
from app.services.rag_service import build_citations, format_context, format_memory, format_timestamp


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


def test_conversation_memory_keeps_recent_exchange() -> None:
    memory = ConversationMemoryService(max_messages=2)
    session_id = "session-1"

    memory.append_exchange(session_id, "Question one", "Answer one")
    memory.append_exchange(session_id, "Question two", "Answer two")

    messages = memory.get_messages(session_id)
    assert messages == [
        ChatMessage(role="user", content="Question two"),
        ChatMessage(role="assistant", content="Answer two"),
    ]
    assert "Question two" in format_memory(messages)
