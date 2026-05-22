from pydantic import BaseModel, Field

from app.schemas.rag import ChatMessage, TimestampCitation
from app.schemas.vectorstore import VectorSearchResult


class CitationQuality(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    has_citations: bool
    has_timestamps: bool
    citation_count: int = Field(ge=0)
    context_coverage: float = Field(default=1.0, ge=0.0, le=1.0)


class EvaluationMetrics(BaseModel):
    groundedness_score: float = Field(ge=0.0, le=1.0)
    hallucination_risk: float = Field(ge=0.0, le=1.0)
    unsupported_claims: list[str]
    citation_quality: CitationQuality
    latency_ms: float = Field(ge=0.0)
    latency_budget_ms: int = Field(gt=0)
    latency_passed: bool
    passed: bool


class RAGEvaluationRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    video_id: str | None = Field(default=None, min_length=6, max_length=32)
    session_id: str | None = Field(default=None, min_length=3, max_length=120)
    top_k: int = Field(default=5, ge=1, le=12)


class RAGEvaluationRun(BaseModel):
    session_id: str
    message: str
    answer: str
    latency_ms: float = Field(ge=0.0)
    video_id: str | None = None


class RAGEvaluationResponse(BaseModel):
    run: RAGEvaluationRun
    metrics: EvaluationMetrics
    citations: list[TimestampCitation]
    retrieved_context: list[VectorSearchResult]
    memory: list[ChatMessage]


class ConversationTurn(BaseModel):
    message: str = Field(min_length=2, max_length=2000)


class ConversationEvaluationRequest(BaseModel):
    video_id: str | None = Field(default=None, min_length=6, max_length=32)
    session_id: str | None = Field(default=None, min_length=3, max_length=120)
    top_k: int = Field(default=5, ge=1, le=12)
    turns: list[ConversationTurn] = Field(min_length=1, max_length=12)


class ConversationEvaluationResponse(BaseModel):
    session_id: str
    total_turns: int = Field(ge=0)
    average_latency_ms: float = Field(ge=0.0)
    average_groundedness_score: float = Field(ge=0.0, le=1.0)
    failed_turns: list[int]
    runs: list[RAGEvaluationResponse]
