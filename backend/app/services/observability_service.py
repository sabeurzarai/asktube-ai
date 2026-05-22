import os
import re
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from langsmith import traceable

from app.core.config import Settings, settings
from app.schemas.evaluation import (
    CitationQuality,
    ConversationEvaluationRequest,
    ConversationEvaluationResponse,
    EvaluationMetrics,
    RAGEvaluationRequest,
    RAGEvaluationResponse,
    RAGEvaluationRun,
)
from app.schemas.rag import RAGChatResponse, TimestampCitation
from app.schemas.vectorstore import VectorSearchResult
from app.services.rag_service import RAGService, get_rag_service

T = TypeVar("T")

WORD_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]{2,}")
NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")
TIMESTAMP_PATTERN = re.compile(r"\b(?:\d{1,2}:)?\d{1,2}:\d{2}\b")


def configure_langsmith(config: Settings = settings) -> None:
    """Expose pydantic .env settings to LangChain/LangSmith runtime clients."""
    if config.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", config.langsmith_api_key)
        os.environ.setdefault("LANGCHAIN_API_KEY", config.langsmith_api_key)

    os.environ.setdefault("LANGSMITH_ENDPOINT", config.langsmith_endpoint)
    os.environ.setdefault("LANGCHAIN_ENDPOINT", config.langsmith_endpoint)
    project_name = config.langchain_project or config.langsmith_project
    os.environ.setdefault("LANGSMITH_PROJECT", project_name)
    os.environ.setdefault("LANGCHAIN_PROJECT", project_name)

    tracing_enabled = (
        config.langsmith_tracing
        if config.langchain_tracing_v2 is None
        else config.langsmith_tracing or config.langchain_tracing_v2
    )
    tracing_value = "true" if tracing_enabled else "false"
    os.environ.setdefault("LANGSMITH_TRACING", tracing_value)
    os.environ.setdefault("LANGCHAIN_TRACING_V2", tracing_value)
    os.environ.setdefault("LANGCHAIN_CALLBACKS_BACKGROUND", "true")


async def timed_async_call(callback: Callable[[], Awaitable[T]]) -> tuple[T, float]:
    start = time.perf_counter()
    result = await callback()
    elapsed_ms = (time.perf_counter() - start) * 1000
    return result, elapsed_ms


class LangSmithEvaluationService:
    def __init__(self, config: Settings, rag_service: RAGService) -> None:
        self.config = config
        self.rag_service = rag_service

    @traceable(name="rag_evaluation", run_type="chain", project_name=settings.langsmith_eval_project)
    async def evaluate_rag(self, request: RAGEvaluationRequest) -> RAGEvaluationResponse:
        response, latency_ms = await timed_async_call(
            lambda: self.rag_service.answer(
                message=request.message,
                video_id=request.video_id,
                session_id=request.session_id,
                top_k=request.top_k,
            )
        )
        metrics = evaluate_response_quality(
            response=response,
            latency_ms=latency_ms,
            latency_budget_ms=self.config.langsmith_latency_budget_ms,
            hallucination_threshold=self.config.hallucination_risk_threshold,
        )

        return RAGEvaluationResponse(
            run=RAGEvaluationRun(
                session_id=response.session_id,
                message=request.message,
                answer=response.answer,
                latency_ms=latency_ms,
                video_id=request.video_id,
            ),
            metrics=metrics,
            citations=response.citations,
            retrieved_context=response.retrieved_context,
            memory=response.memory,
        )

    @traceable(
        name="conversation_evaluation",
        run_type="chain",
        project_name=settings.langsmith_eval_project,
    )
    async def evaluate_conversation(
        self,
        request: ConversationEvaluationRequest,
    ) -> ConversationEvaluationResponse:
        session_id = request.session_id
        runs: list[RAGEvaluationResponse] = []

        for turn in request.turns:
            result = await self.evaluate_rag(
                RAGEvaluationRequest(
                    message=turn.message,
                    video_id=request.video_id,
                    session_id=session_id,
                    top_k=request.top_k,
                )
            )
            session_id = result.run.session_id
            runs.append(result)

        average_latency = (
            sum(run.run.latency_ms for run in runs) / len(runs)
            if runs
            else 0.0
        )
        average_groundedness = (
            sum(run.metrics.groundedness_score for run in runs) / len(runs)
            if runs
            else 0.0
        )
        failed_turns = [
            index
            for index, run in enumerate(runs)
            if run.metrics.hallucination_risk >= self.config.hallucination_risk_threshold
            or not run.metrics.passed
        ]

        return ConversationEvaluationResponse(
            session_id=session_id or "",
            total_turns=len(runs),
            average_latency_ms=average_latency,
            average_groundedness_score=average_groundedness,
            failed_turns=failed_turns,
            runs=runs,
        )


def evaluate_response_quality(
    response: RAGChatResponse,
    latency_ms: float,
    latency_budget_ms: int,
    hallucination_threshold: float,
) -> EvaluationMetrics:
    context_text = " ".join(result.text for result in response.retrieved_context)
    citation_quality = evaluate_citations(response.citations, response.retrieved_context)
    unsupported_claims = find_unsupported_claims(response.answer, context_text)
    groundedness_score = calculate_groundedness(response.answer, context_text)
    answer_refusal = is_transcript_refusal(response.answer)
    no_context = not response.retrieved_context

    if no_context and answer_refusal:
        hallucination_risk = 0.0
    else:
        hallucination_risk = min(
            1.0,
            (1.0 - groundedness_score) * 0.65
            + min(len(unsupported_claims), 5) * 0.07
            + (0.15 if not citation_quality.has_timestamps else 0.0),
        )

    latency_passed = latency_ms <= latency_budget_ms
    passed = (
        hallucination_risk < hallucination_threshold
        and citation_quality.score >= 0.7
        and latency_passed
    )

    return EvaluationMetrics(
        groundedness_score=round(groundedness_score, 3),
        hallucination_risk=round(hallucination_risk, 3),
        unsupported_claims=unsupported_claims,
        citation_quality=citation_quality,
        latency_ms=round(latency_ms, 2),
        latency_budget_ms=latency_budget_ms,
        latency_passed=latency_passed,
        passed=passed,
    )


def evaluate_citations(
    citations: list[TimestampCitation],
    context: list[VectorSearchResult],
) -> CitationQuality:
    if not context:
        return CitationQuality(
            score=1.0 if not citations else 0.7,
            has_citations=not citations,
            has_timestamps=not citations,
            citation_count=len(citations),
        )

    has_citations = bool(citations)
    has_timestamps = all(TIMESTAMP_PATTERN.search(citation.timestamp) for citation in citations)
    cited_chunk_ids = {citation.chunk_id for citation in citations}
    context_chunk_ids = {result.chunk_id for result in context}
    context_coverage = (
        len(cited_chunk_ids & context_chunk_ids) / len(context_chunk_ids)
        if context_chunk_ids
        else 1.0
    )
    score = (
        (0.35 if has_citations else 0.0)
        + (0.35 if has_timestamps else 0.0)
        + (0.30 * context_coverage)
    )

    return CitationQuality(
        score=round(score, 3),
        has_citations=has_citations,
        has_timestamps=has_timestamps,
        citation_count=len(citations),
        context_coverage=round(context_coverage, 3),
    )


def calculate_groundedness(answer: str, context: str) -> float:
    answer_terms = extract_signal_terms(answer)
    if not answer_terms:
        return 1.0

    context_terms = extract_signal_terms(context)
    supported_terms = answer_terms & context_terms
    return len(supported_terms) / len(answer_terms)


def find_unsupported_claims(answer: str, context: str) -> list[str]:
    context_terms = extract_signal_terms(context)
    unsupported_numbers = [
        number for number in NUMBER_PATTERN.findall(answer) if number.lower() not in context.lower()
    ]
    unsupported_terms = sorted(extract_signal_terms(answer) - context_terms)
    return (unsupported_numbers + unsupported_terms)[:12]


def extract_signal_terms(text: str) -> set[str]:
    stopwords = {
        "about",
        "also",
        "answer",
        "because",
        "cannot",
        "context",
        "could",
        "from",
        "have",
        "into",
        "only",
        "that",
        "their",
        "there",
        "these",
        "this",
        "transcript",
        "using",
        "video",
        "what",
        "when",
        "where",
        "which",
        "with",
        "would",
        "your",
    }
    return {
        term.lower().strip("'")
        for term in WORD_PATTERN.findall(text)
        if term.lower() not in stopwords
    }


def is_transcript_refusal(answer: str) -> bool:
    normalized = answer.lower()
    return "cannot answer" in normalized and "transcript" in normalized


def get_evaluation_service() -> LangSmithEvaluationService:
    return LangSmithEvaluationService(config=settings, rag_service=get_rag_service())
