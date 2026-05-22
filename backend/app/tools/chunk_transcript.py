from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.schemas.transcript import TranscriptResponse
from app.services.chunking_service import ChunkingOptions, ChunkingService


class ChunkTranscriptInput(BaseModel):
    transcript: dict = Field(description="TranscriptResponse object serialized as a dict")
    max_chunk_chars: int = Field(
        default=1200,
        ge=100,
        description="Maximum number of characters per chunk",
    )
    overlap_segments: int = Field(
        default=1,
        ge=0,
        description="Number of overlapping transcript segments between adjacent chunks",
    )
    include_embeddings: bool = Field(
        default=False,
        description="Generate OpenAI embeddings for each chunk",
    )


def make_chunk_transcript_tool(service: ChunkingService) -> StructuredTool:
    async def _run(
        transcript: dict,
        max_chunk_chars: int = 1200,
        overlap_segments: int = 1,
        include_embeddings: bool = False,
    ) -> dict:
        transcript_obj = TranscriptResponse.model_validate(transcript)
        options = ChunkingOptions(
            max_chunk_chars=max_chunk_chars,
            overlap_segments=overlap_segments,
            include_embeddings=include_embeddings,
        )
        chunks, embedding_model = await service.chunk_transcript(
            transcript=transcript_obj,
            options=options,
        )
        return {
            "chunks": [chunk.model_dump() for chunk in chunks],
            "chunk_count": len(chunks),
            "embedding_model": embedding_model,
        }

    return StructuredTool.from_function(
        coroutine=_run,
        name="chunk_transcript",
        description=(
            "Split a video transcript into semantically coherent chunks that preserve "
            "timestamp boundaries. Optionally generates OpenAI embeddings for each chunk."
        ),
        args_schema=ChunkTranscriptInput,
    )
