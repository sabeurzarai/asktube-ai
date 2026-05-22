from fastapi import APIRouter, Depends

from app.schemas.evaluation import (
    ConversationEvaluationRequest,
    ConversationEvaluationResponse,
    RAGEvaluationRequest,
    RAGEvaluationResponse,
)
from app.services.observability_service import LangSmithEvaluationService, get_evaluation_service

router = APIRouter()


@router.post("/evaluations/rag", response_model=RAGEvaluationResponse)
async def evaluate_rag_response(
    request: RAGEvaluationRequest,
    service: LangSmithEvaluationService = Depends(get_evaluation_service),
) -> RAGEvaluationResponse:
    return await service.evaluate_rag(request)


@router.post("/evaluations/conversation", response_model=ConversationEvaluationResponse)
async def evaluate_conversation(
    request: ConversationEvaluationRequest,
    service: LangSmithEvaluationService = Depends(get_evaluation_service),
) -> ConversationEvaluationResponse:
    return await service.evaluate_conversation(request)
