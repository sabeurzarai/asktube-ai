from langchain_core.tools import StructuredTool

from app.services.chunking_service import get_chunking_service
from app.services.rag_service import get_rag_service
from app.services.transcript_service import get_transcript_service
from app.services.vectorstore_service import get_vectorstore_service
from app.services.youtube_service import get_youtube_service
from app.tools.answer_question import make_answer_question_tool
from app.tools.chunk_transcript import make_chunk_transcript_tool
from app.tools.extract_transcript import make_extract_transcript_tool
from app.tools.ingest_video import make_ingest_video_tool
from app.tools.retrieve_context import make_retrieve_context_tool
from app.tools.search_youtube_videos import make_search_youtube_videos_tool
from app.tools.store_video_vectors import make_store_video_vectors_tool


def get_tools() -> list[StructuredTool]:
    """Return all AskTube AI LangChain tools wired to their production services."""
    vectorstore = get_vectorstore_service()
    transcript = get_transcript_service()
    chunking = get_chunking_service()
    return [
        make_search_youtube_videos_tool(get_youtube_service()),
        make_extract_transcript_tool(transcript),
        make_chunk_transcript_tool(chunking),
        make_store_video_vectors_tool(vectorstore),
        make_ingest_video_tool(transcript, chunking, vectorstore),
        make_retrieve_context_tool(vectorstore),
        make_answer_question_tool(get_rag_service()),
    ]


__all__ = [
    "get_tools",
    "make_answer_question_tool",
    "make_chunk_transcript_tool",
    "make_extract_transcript_tool",
    "make_ingest_video_tool",
    "make_retrieve_context_tool",
    "make_search_youtube_videos_tool",
    "make_store_video_vectors_tool",
]
