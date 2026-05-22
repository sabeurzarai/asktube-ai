from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services.rag_service import RAGService


class AnswerQuestionInput(BaseModel):
    message: str = Field(description="User question to answer using transcript-grounded RAG")
    video_id: str | None = Field(
        default=None,
        description="Optional YouTube video ID to restrict context to a specific video",
    )
    session_id: str | None = Field(
        default=None,
        description="Session ID for conversation memory continuity across turns",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=12,
        description="Number of transcript chunks to retrieve as RAG context",
    )


def make_answer_question_tool(service: RAGService) -> StructuredTool:
    async def _run(
        message: str,
        video_id: str | None = None,
        session_id: str | None = None,
        top_k: int = 5,
    ) -> dict:
        result = await service.answer(
            message=message,
            video_id=video_id,
            session_id=session_id,
            top_k=top_k,
        )
        return result.model_dump()

    return StructuredTool.from_function(
        coroutine=_run,
        name="answer_question",
        description=(
            "Answer a user question about a YouTube video using RAG "
            "(Retrieval-Augmented Generation). Retrieves relevant transcript chunks "
            "and returns a grounded answer with timestamp citations."
        ),
        args_schema=AnswerQuestionInput,
    )
