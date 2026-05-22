from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.schemas.chunks import TranscriptChunk
from app.services.vectorstore_service import ChromaVectorStoreService


class StoreVideoVectorsInput(BaseModel):
    chunks: list[dict] = Field(
        description="List of TranscriptChunk objects serialized as dicts to upsert into ChromaDB"
    )


def make_store_video_vectors_tool(service: ChromaVectorStoreService) -> StructuredTool:
    async def _run(chunks: list[dict]) -> dict:
        chunk_objects = [TranscriptChunk.model_validate(chunk) for chunk in chunks]
        stored_ids = await service.upsert_chunks(chunk_objects)
        return {"stored_chunk_ids": stored_ids, "count": len(stored_ids)}

    return StructuredTool.from_function(
        coroutine=_run,
        name="store_video_vectors",
        description=(
            "Upsert transcript chunks into the ChromaDB vector store. "
            "Generates OpenAI embeddings automatically for any chunk that lacks them."
        ),
        args_schema=StoreVideoVectorsInput,
    )
