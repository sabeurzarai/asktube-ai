from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services.vectorstore_service import ChromaVectorStoreService


class RetrieveContextInput(BaseModel):
    query: str = Field(description="Natural language query to search for relevant transcript context")
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of ranked results to return",
    )
    video_id: str | None = Field(
        default=None,
        description="Optional YouTube video ID to restrict the search to a single video",
    )


def make_retrieve_context_tool(service: ChromaVectorStoreService) -> StructuredTool:
    async def _run(query: str, limit: int = 5, video_id: str | None = None) -> dict:
        results = await service.similarity_search(query=query, limit=limit, video_id=video_id)
        return {
            "results": [result.model_dump() for result in results],
            "result_count": len(results),
        }

    return StructuredTool.from_function(
        coroutine=_run,
        name="retrieve_context",
        description=(
            "Retrieve the most semantically relevant transcript chunks from the vector store "
            "for a given natural-language query. Optionally filter by YouTube video ID."
        ),
        args_schema=RetrieveContextInput,
    )
