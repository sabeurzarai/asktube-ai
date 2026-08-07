from fastapi.testclient import TestClient

from app.api.routes.evaluations import get_evaluation_service
from app.main import app
from app.schemas.evaluation import RAGEvaluationResponse
from app.schemas.rag import ChatMessage, RAGChatResponse, TimestampCitation
from app.schemas.vectorstore import VectorSearchResult
from app.services.observability_service import (
    calculate_groundedness,
    evaluate_response_quality,
    find_unsupported_claims,
)


def make_context() -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id="video123:0:test",
        video_id="video123",
        text="The transcript says retrieval should happen before generation and cites timestamps.",
        start_seconds=12.0,
        end_seconds=42.0,
        segment_indices=[0],
        distance=0.1,
        metadata={"source": "youtube_transcript_api"},
    )


def make_response(answer: str) -> RAGChatResponse:
    context = make_context()
    return RAGChatResponse(
        session_id="session-1",
        answer=answer,
        citations=[
            TimestampCitation(
                chunk_id=context.chunk_id,
                video_id=context.video_id,
                start_seconds=context.start_seconds,
                end_seconds=context.end_seconds,
                timestamp="00:12-00:42",
                text=context.text,
            )
        ],
        retrieved_context=[context],
        memory=[ChatMessage(role="user", content="What happens first?")],
    )


def test_groundedness_scores_supported_answer_higher_than_unsupported_answer() -> None:
    supported = calculate_groundedness(
        "Retrieval should happen before generation.",
        make_context().text,
    )
    unsupported = calculate_groundedness(
        "The video recommends Kubernetes and quantum databases.",
        make_context().text,
    )

    assert supported > unsupported
    assert unsupported < 0.5


def test_hallucination_detection_flags_terms_outside_transcript() -> None:
    unsupported = find_unsupported_claims(
        "The speaker recommends Kubernetes and quantum databases in 2030.",
        make_context().text,
    )

    assert "kubernetes" in unsupported
    assert "quantum" in unsupported
    assert "2030" in unsupported


def test_evaluate_response_quality_checks_latency_citations_and_grounding() -> None:
    metrics = evaluate_response_quality(
        response=make_response("Retrieval should happen before generation."),
        latency_ms=250.0,
        latency_budget_ms=1000,
        hallucination_threshold=0.35,
    )

    assert metrics.passed is True
    assert metrics.latency_passed is True
    assert metrics.citation_quality.has_timestamps is True
    assert metrics.hallucination_risk < 0.35


def make_summary_response(answer: str) -> RAGChatResponse:
    """A response shaped like the summarisation path: retrieved_context is
    empty on purpose (no chunk selection took place - see RAGService.answer),
    but citations are still populated from validated timestamps.
    """
    return RAGChatResponse(
        session_id="session-1",
        answer=answer,
        citations=[
            TimestampCitation(
                chunk_id="video123:0:test",
                video_id="video123",
                start_seconds=12.0,
                end_seconds=42.0,
                timestamp="00:12-00:42",
                text="The transcript says retrieval should happen before generation.",
            )
        ],
        retrieved_context=[],
        memory=[ChatMessage(role="user", content="What is this video about?")],
    )


def test_evaluate_response_quality_judges_the_summary_path_by_its_citations() -> None:
    # The summarisation path (broad questions) returns retrieved_context=[] on
    # purpose. Before this test's fix, that empty context made every summary
    # answer score as ungrounded (groundedness 0.0, hallucination_risk 1.0)
    # and its real citations as uncited (has_citations False despite
    # citation_count > 0) - self-contradictory, and wrong given the citations
    # were validated against real chunks. Judging against the citations
    # instead should score a grounded, on-topic answer as passing.
    metrics = evaluate_response_quality(
        response=make_summary_response("Retrieval should happen before generation."),
        latency_ms=250.0,
        latency_budget_ms=1000,
        hallucination_threshold=0.35,
    )

    assert metrics.citation_quality.has_citations is True
    assert metrics.citation_quality.citation_count == 1
    assert metrics.groundedness_score > 0.0
    assert metrics.hallucination_risk < 1.0
    assert metrics.passed is True


class FakeEvaluationService:
    async def evaluate_rag(self, request):  # noqa: ANN001
        response = make_response(f"Answered: {request.message}")
        metrics = evaluate_response_quality(
            response=response,
            latency_ms=10.0,
            latency_budget_ms=1000,
            hallucination_threshold=0.8,
        )
        return RAGEvaluationResponse(
            run={
                "session_id": response.session_id,
                "message": request.message,
                "answer": response.answer,
                "latency_ms": 10.0,
                "video_id": request.video_id,
            },
            metrics=metrics,
            citations=response.citations,
            retrieved_context=response.retrieved_context,
            memory=response.memory,
        )


def test_rag_evaluation_route_returns_quality_metrics() -> None:
    app.dependency_overrides[get_evaluation_service] = lambda: FakeEvaluationService()
    client = TestClient(app)

    response = client.post(
        "/api/evaluations/rag",
        json={"message": "What happens first?", "video_id": "video123"},
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["message"] == "What happens first?"
    assert payload["metrics"]["latency_ms"] == 10.0
    assert payload["metrics"]["citation_quality"]["has_timestamps"] is True
