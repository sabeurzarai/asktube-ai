import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.schemas.chunks import TranscriptChunk
from app.schemas.rag import ChatMessage, RAGChatResponse, TimestampCitation
from app.schemas.search import YouTubeSearchResponse, YouTubeVideo
from app.schemas.transcript import TranscriptResponse, TranscriptSegment
from app.schemas.vectorstore import VectorSearchResult
from app.services.chunking_service import ChunkingOptions
from app.services.transcript_service import TranscriptFetchOptions
from app.tools.answer_question import make_answer_question_tool
from app.tools.chunk_transcript import make_chunk_transcript_tool
from app.tools.extract_transcript import make_extract_transcript_tool
from app.tools.retrieve_context import make_retrieve_context_tool
from app.tools.search_youtube_videos import make_search_youtube_videos_tool
from app.tools.store_video_vectors import make_store_video_vectors_tool


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------


def make_video() -> YouTubeVideo:
    return YouTubeVideo(
        video_id="abc123",
        title="Learn Python",
        description="A Python tutorial",
        channel_id="ch1",
        channel_title="TutorialChannel",
        published_at="2024-01-01T00:00:00Z",
        thumbnail_url=None,
        thumbnails={},
        duration=None,
        duration_seconds=None,
        view_count=1000,
        like_count=50,
        comment_count=10,
        youtube_url="https://www.youtube.com/watch?v=abc123",
    )


def make_transcript() -> TranscriptResponse:
    return TranscriptResponse(
        video_id="abc123",
        language="en",
        source="youtube_transcript_api",
        segment_count=2,
        full_text="Hello world. This is a test.",
        segments=[
            TranscriptSegment(
                index=0, start_seconds=0.0, end_seconds=5.0, duration_seconds=5.0, text="Hello world."
            ),
            TranscriptSegment(
                index=1, start_seconds=5.0, end_seconds=10.0, duration_seconds=5.0, text="This is a test."
            ),
        ],
    )


def make_chunk() -> TranscriptChunk:
    return TranscriptChunk(
        chunk_id="abc123:0:deadbeef0000",
        index=0,
        video_id="abc123",
        text="Hello world. This is a test.",
        start_seconds=0.0,
        end_seconds=10.0,
        segment_indices=[0, 1],
        token_estimate=7,
        metadata={
            "video_id": "abc123",
            "source": "youtube_transcript_api",
            "language": "en",
            "chunk_index": 0,
            "start_seconds": 0.0,
            "end_seconds": 10.0,
            "segment_indices": [0, 1],
        },
    )


def make_vector_result() -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id="abc123:0:deadbeef0000",
        video_id="abc123",
        text="Hello world. This is a test.",
        start_seconds=0.0,
        end_seconds=10.0,
        segment_indices=[0, 1],
        distance=0.05,
        metadata={"source": "youtube_transcript_api"},
    )


def make_rag_response() -> RAGChatResponse:
    return RAGChatResponse(
        session_id="session-xyz",
        answer="The transcript says hello world.",
        citations=[
            TimestampCitation(
                chunk_id="abc123:0:deadbeef0000",
                video_id="abc123",
                start_seconds=0.0,
                end_seconds=10.0,
                timestamp="00:00-00:10",
                text="Hello world. This is a test.",
            )
        ],
        retrieved_context=[make_vector_result()],
        memory=[ChatMessage(role="user", content="What does the video say?")],
    )


# ---------------------------------------------------------------------------
# search_youtube_videos
# ---------------------------------------------------------------------------


def test_search_youtube_videos_calls_service_with_args() -> None:
    service = MagicMock()
    service.search_videos = AsyncMock(
        return_value=YouTubeSearchResponse(query="python tutorial", count=1, videos=[make_video()])
    )

    tool = make_search_youtube_videos_tool(service)
    result = asyncio.run(tool.ainvoke({"query": "python tutorial", "max_results": 5}))

    service.search_videos.assert_called_once_with(query="python tutorial", max_results=5)
    assert result["query"] == "python tutorial"
    assert result["count"] == 1
    assert result["videos"][0]["video_id"] == "abc123"


def test_search_youtube_videos_uses_default_max_results() -> None:
    service = MagicMock()
    service.search_videos = AsyncMock(
        return_value=YouTubeSearchResponse(query="q", count=0, videos=[])
    )

    tool = make_search_youtube_videos_tool(service)
    asyncio.run(tool.ainvoke({"query": "q"}))

    service.search_videos.assert_called_once_with(query="q", max_results=10)


def test_search_youtube_videos_tool_name() -> None:
    tool = make_search_youtube_videos_tool(MagicMock())
    assert tool.name == "search_youtube_videos"


# ---------------------------------------------------------------------------
# extract_transcript
# ---------------------------------------------------------------------------


def test_extract_transcript_calls_service_with_options() -> None:
    service = MagicMock()
    service.get_transcript = AsyncMock(return_value=make_transcript())

    tool = make_extract_transcript_tool(service)
    result = asyncio.run(tool.ainvoke({"video_id": "abc123"}))

    service.get_transcript.assert_called_once_with(
        video_id="abc123",
        options=TranscriptFetchOptions(language="en", use_whisper_fallback=True),
    )
    assert result["video_id"] == "abc123"
    assert result["segment_count"] == 2
    assert result["source"] == "youtube_transcript_api"


def test_extract_transcript_forwards_language_and_fallback() -> None:
    service = MagicMock()
    service.get_transcript = AsyncMock(return_value=make_transcript())

    tool = make_extract_transcript_tool(service)
    asyncio.run(tool.ainvoke({"video_id": "abc123", "language": "es", "use_whisper_fallback": False}))

    service.get_transcript.assert_called_once_with(
        video_id="abc123",
        options=TranscriptFetchOptions(language="es", use_whisper_fallback=False),
    )


def test_extract_transcript_tool_name() -> None:
    tool = make_extract_transcript_tool(MagicMock())
    assert tool.name == "extract_transcript"


# ---------------------------------------------------------------------------
# chunk_transcript
# ---------------------------------------------------------------------------


def test_chunk_transcript_calls_service_with_correct_options() -> None:
    chunk = make_chunk()
    service = MagicMock()
    service.chunk_transcript = AsyncMock(return_value=([chunk], None))

    tool = make_chunk_transcript_tool(service)
    result = asyncio.run(tool.ainvoke({"transcript": make_transcript().model_dump()}))

    service.chunk_transcript.assert_called_once()
    kwargs = service.chunk_transcript.call_args.kwargs
    assert kwargs["options"] == ChunkingOptions(
        max_chunk_chars=1200, overlap_segments=1, include_embeddings=False
    )
    assert result["chunk_count"] == 1
    assert result["chunks"][0]["video_id"] == "abc123"
    assert result["embedding_model"] is None


def test_chunk_transcript_forwards_custom_options() -> None:
    service = MagicMock()
    service.chunk_transcript = AsyncMock(return_value=([], "text-embedding-3-small"))

    tool = make_chunk_transcript_tool(service)
    asyncio.run(tool.ainvoke({
        "transcript": make_transcript().model_dump(),
        "max_chunk_chars": 800,
        "overlap_segments": 2,
        "include_embeddings": True,
    }))

    kwargs = service.chunk_transcript.call_args.kwargs
    assert kwargs["options"] == ChunkingOptions(
        max_chunk_chars=800, overlap_segments=2, include_embeddings=True
    )


def test_chunk_transcript_deserializes_transcript_dict() -> None:
    """Tool must reconstruct a TranscriptResponse from the dict before calling the service."""
    service = MagicMock()
    service.chunk_transcript = AsyncMock(return_value=([], None))

    tool = make_chunk_transcript_tool(service)
    asyncio.run(tool.ainvoke({"transcript": make_transcript().model_dump()}))

    transcript_arg = service.chunk_transcript.call_args.kwargs["transcript"]
    assert isinstance(transcript_arg, TranscriptResponse)
    assert transcript_arg.video_id == "abc123"


def test_chunk_transcript_tool_name() -> None:
    tool = make_chunk_transcript_tool(MagicMock())
    assert tool.name == "chunk_transcript"


# ---------------------------------------------------------------------------
# store_video_vectors
# ---------------------------------------------------------------------------


def test_store_video_vectors_calls_service_with_chunk_objects() -> None:
    service = MagicMock()
    service.upsert_chunks = AsyncMock(return_value=["abc123:0:deadbeef0000"])

    tool = make_store_video_vectors_tool(service)
    result = asyncio.run(tool.ainvoke({"chunks": [make_chunk().model_dump()]}))

    service.upsert_chunks.assert_called_once()
    stored = service.upsert_chunks.call_args.args[0]
    assert len(stored) == 1
    assert isinstance(stored[0], TranscriptChunk)
    assert stored[0].chunk_id == "abc123:0:deadbeef0000"
    assert result["stored_chunk_ids"] == ["abc123:0:deadbeef0000"]
    assert result["count"] == 1


def test_store_video_vectors_empty_list() -> None:
    service = MagicMock()
    service.upsert_chunks = AsyncMock(return_value=[])

    tool = make_store_video_vectors_tool(service)
    result = asyncio.run(tool.ainvoke({"chunks": []}))

    assert result["count"] == 0
    assert result["stored_chunk_ids"] == []


def test_store_video_vectors_tool_name() -> None:
    tool = make_store_video_vectors_tool(MagicMock())
    assert tool.name == "store_video_vectors"


# ---------------------------------------------------------------------------
# retrieve_context
# ---------------------------------------------------------------------------


def test_retrieve_context_calls_service_with_all_args() -> None:
    service = MagicMock()
    service.similarity_search = AsyncMock(return_value=[make_vector_result()])

    tool = make_retrieve_context_tool(service)
    result = asyncio.run(tool.ainvoke({"query": "hello world", "limit": 3, "video_id": "abc123"}))

    service.similarity_search.assert_called_once_with(query="hello world", limit=3, video_id="abc123")
    assert result["result_count"] == 1
    assert result["results"][0]["chunk_id"] == "abc123:0:deadbeef0000"


def test_retrieve_context_uses_defaults() -> None:
    service = MagicMock()
    service.similarity_search = AsyncMock(return_value=[])

    tool = make_retrieve_context_tool(service)
    asyncio.run(tool.ainvoke({"query": "test"}))

    service.similarity_search.assert_called_once_with(query="test", limit=5, video_id=None)


def test_retrieve_context_tool_name() -> None:
    tool = make_retrieve_context_tool(MagicMock())
    assert tool.name == "retrieve_context"


# ---------------------------------------------------------------------------
# answer_question
# ---------------------------------------------------------------------------


def test_answer_question_calls_service_with_all_args() -> None:
    service = MagicMock()
    service.answer = AsyncMock(return_value=make_rag_response())

    tool = make_answer_question_tool(service)
    result = asyncio.run(tool.ainvoke({
        "message": "What does the video say?",
        "video_id": "abc123",
        "session_id": "session-xyz",
        "top_k": 3,
    }))

    service.answer.assert_called_once_with(
        message="What does the video say?",
        video_id="abc123",
        session_id="session-xyz",
        top_k=3,
    )
    assert result["session_id"] == "session-xyz"
    assert result["answer"] == "The transcript says hello world."
    assert len(result["citations"]) == 1
    assert result["citations"][0]["video_id"] == "abc123"


def test_answer_question_uses_defaults() -> None:
    service = MagicMock()
    service.answer = AsyncMock(return_value=make_rag_response())

    tool = make_answer_question_tool(service)
    asyncio.run(tool.ainvoke({"message": "What?"}))

    service.answer.assert_called_once_with(
        message="What?",
        video_id=None,
        session_id=None,
        top_k=5,
    )


def test_answer_question_tool_name() -> None:
    tool = make_answer_question_tool(MagicMock())
    assert tool.name == "answer_question"


# ---------------------------------------------------------------------------
# Registry - all tool names are unique and well-formed
# ---------------------------------------------------------------------------


def test_all_tool_names_are_correct() -> None:
    tools = [
        make_search_youtube_videos_tool(MagicMock()),
        make_extract_transcript_tool(MagicMock()),
        make_chunk_transcript_tool(MagicMock()),
        make_store_video_vectors_tool(MagicMock()),
        make_retrieve_context_tool(MagicMock()),
        make_answer_question_tool(MagicMock()),
    ]
    assert [t.name for t in tools] == [
        "search_youtube_videos",
        "extract_transcript",
        "chunk_transcript",
        "store_video_vectors",
        "retrieve_context",
        "answer_question",
    ]


def test_all_tools_have_descriptions() -> None:
    tools = [
        make_search_youtube_videos_tool(MagicMock()),
        make_extract_transcript_tool(MagicMock()),
        make_chunk_transcript_tool(MagicMock()),
        make_store_video_vectors_tool(MagicMock()),
        make_retrieve_context_tool(MagicMock()),
        make_answer_question_tool(MagicMock()),
    ]
    for tool in tools:
        assert tool.description, f"{tool.name} must have a description"
