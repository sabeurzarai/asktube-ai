from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.chunking_service import ChunkingOptions, ChunkingService
from app.services.transcript_service import TranscriptFetchOptions, TranscriptService
from app.services.vectorstore_service import VectorStoreService


class IngestVideoInput(BaseModel):
    video_id: str = Field(description="YouTube video ID to extract, chunk, and store in the vector store")
    language: str = Field(default="en", description="BCP-47 language code for transcript extraction")


def make_ingest_video_tool(
    transcript_service: TranscriptService,
    chunking_service: ChunkingService,
    vectorstore_service: VectorStoreService,
) -> StructuredTool:
    async def _run(video_id: str, language: str = "en") -> dict:
        transcript = await transcript_service.get_transcript(
            video_id=video_id,
            options=TranscriptFetchOptions(language=language, use_whisper_fallback=True),
        )
        chunks, embedding_model = await chunking_service.chunk_transcript(
            transcript=transcript,
            options=ChunkingOptions(
                max_chunk_chars=settings.chunk_max_chars,
                overlap_segments=settings.chunk_overlap_segments,
                include_embeddings=True,
            ),
        )
        stored_ids = await vectorstore_service.upsert_chunks(chunks)
        return {
            "video_id": video_id,
            "chunk_count": len(stored_ids),
            "embedding_model": embedding_model or "text-embedding-3-small",
            "status": "ingested",
        }

    return StructuredTool.from_function(
        coroutine=_run,
        name="ingest_video",
        description=(
            "Extract the transcript from a YouTube video, split it into semantic chunks, "
            "generate embeddings, and store everything in the vector store. "
            "Always call this before answer_question when the video has not been ingested yet."
        ),
        args_schema=IngestVideoInput,
    )
