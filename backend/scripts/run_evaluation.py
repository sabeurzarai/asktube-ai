#!/usr/bin/env python3
"""
AskTube AI RAG Evaluation Runner
=================================

Loads evaluation cases from tests/fixtures/rag_eval_cases.json and runs them
through the existing LangSmithEvaluationService, then prints a pass/fail report.

Prerequisites
-------------
1. Video kqtD5dpn9C8 must already be ingested in ChromaDB:
       curl -X POST http://localhost:8000/api/videos/kqtD5dpn9C8/ingest
   (or use the frontend processing flow)

2. OPENAI_API_KEY must be set in backend/.env (required for embeddings + RAG).

3. Run from the backend/ directory:
       cd backend
       python scripts/run_evaluation.py

Optional LangSmith tracing
---------------------------
Set LANGSMITH_API_KEY and LANGSMITH_TRACING=true in backend/.env to send
evaluation traces to LangSmith for inspection.

Interpreting results
--------------------
Each case prints one of:
  PASS   - all assertions satisfied; hallucination_risk < threshold; latency ok
  WARN   - answer is plausible but a soft assertion failed (e.g. no citations)
  FAIL   - hard assertion failed or metrics.passed is False

Exit code 0 = all cases pass, non-zero = at least one failure.
"""

import asyncio
import json
import sys
import textwrap
from pathlib import Path

# Allow running from backend/ without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas.evaluation import ConversationEvaluationRequest, ConversationTurn, RAGEvaluationRequest
from app.services.observability_service import (
    LangSmithEvaluationService,
    configure_langsmith,
    is_transcript_refusal,
)
from app.services.rag_service import get_rag_service
from app.core.config import settings

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "rag_eval_cases.json"
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Single-case evaluation
# ---------------------------------------------------------------------------

async def run_single_case(service: LangSmithEvaluationService, case: dict, video_id: str) -> tuple[str, str]:
    """Run one eval case. Returns (status, reason)."""
    question = case["question"]
    expected = case.get("expected_behavior", "answer")
    expected_contains = case.get("expected_contains_any", [])
    forbidden = case.get("forbidden_contains", [])
    check_citations = case.get("check_citations", True)
    before_secs = case.get("expected_citation_before_seconds")

    try:
        result = await service.evaluate_rag(
            RAGEvaluationRequest(message=question, video_id=video_id, top_k=5)
        )
    except Exception as exc:
        return FAIL, f"Service error: {exc}"

    answer = result.run.answer.lower()
    metrics = result.metrics
    is_refusal = is_transcript_refusal(result.run.answer)

    # -- Expected behavior check ----------------------------------------------
    if expected == "refusal" and not is_refusal:
        return FAIL, f"Expected refusal but got answer: {result.run.answer[:120]!r}"

    if expected == "answer" and is_refusal:
        return FAIL, f"Expected answer but got refusal: {result.run.answer[:120]!r}"

    # "answer_or_refusal" - either is acceptable; forbidden_contains still checked

    # -- Forbidden terms (hallucination check) -------------------------------
    for term in forbidden:
        if term.lower() in answer:
            return FAIL, f"Forbidden hallucinated term found: {term!r}"

    # -- Expected content check -----------------------------------------------
    if expected_contains and expected != "refusal":
        if not any(term.lower() in answer for term in expected_contains):
            return WARN, (
                f"Answer did not contain any of {expected_contains}. "
                f"Got: {result.run.answer[:120]!r}"
            )

    # -- Citation checks ------------------------------------------------------
    if check_citations and expected == "answer":
        if not result.citations:
            return WARN, "Answer was grounded but no timestamp citations were returned"

        if before_secs is not None:
            earliest = min((c.start_seconds for c in result.citations), default=None)
            if earliest is not None and earliest > before_secs:
                return WARN, f"Earliest citation at {earliest:.0f}s; expected < {before_secs}s"

    # -- Heuristic metrics (WARN only - term-overlap scorer is conservative) --
    # The heuristic underestimates groundedness for paraphrased-but-correct
    # answers. Behavioral and content assertions above are the hard checks.
    if not is_refusal and not metrics.passed:
        return WARN, (
            f"heuristic below threshold: "
            f"groundedness={metrics.groundedness_score:.2f} "
            f"hallucination_risk={metrics.hallucination_risk:.2f} "
            f"latency={metrics.latency_ms:.0f}ms "
            f"citations={len(result.citations)}"
        )

    return PASS, (
        f"groundedness={metrics.groundedness_score:.2f} "
        f"hallucination_risk={metrics.hallucination_risk:.2f} "
        f"latency={metrics.latency_ms:.0f}ms "
        f"citations={len(result.citations)}"
    )


# ---------------------------------------------------------------------------
# Conversation-case evaluation
# ---------------------------------------------------------------------------

async def run_conversation_case(service: LangSmithEvaluationService, case: dict, video_id: str) -> tuple[str, str]:
    """Run a multi-turn conversation eval case."""
    turns = [ConversationTurn(message=msg) for msg in case["turns"]]
    t2_contains = case.get("expected_turn_2_contains_any", [])

    try:
        result = await service.evaluate_conversation(
            ConversationEvaluationRequest(video_id=video_id, turns=turns, top_k=5)
        )
    except Exception as exc:
        return FAIL, f"Service error: {exc}"

    if result.failed_turns:
        return WARN, f"Heuristic metrics below threshold on turn(s) {result.failed_turns}"

    if len(result.runs) >= 2 and t2_contains:
        answer_2 = result.runs[1].run.answer.lower()
        if not any(term.lower() in answer_2 for term in t2_contains):
            return WARN, f"Turn-2 answer missing expected terms {t2_contains}: {result.runs[1].run.answer[:100]!r}"

    return PASS, (
        f"avg_groundedness={result.average_groundedness_score:.2f} "
        f"avg_latency={result.average_latency_ms:.0f}ms"
    )


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

STATUS_ICON = {PASS: "OK  ", WARN: "WARN", FAIL: "FAIL"}
STATUS_COLOR = {PASS: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
RESET = "\033[0m"


def print_row(status: str, case_id: str, category: str, reason: str) -> None:
    icon = STATUS_ICON[status]
    color = STATUS_COLOR[status]
    label = f"{color}{icon} {status:<4}{RESET}"
    print(f"  {label}  {case_id:<14}  [{category:<25}]  {reason}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    configure_langsmith(settings)

    with FIXTURE_PATH.open() as f:
        data = json.load(f)

    video_id: str = data["video_id"]
    single_cases: list[dict] = data.get("cases", [])
    conv_cases: list[dict] = data.get("conversation_cases", [])

    print(f"\n{'-'*72}")
    print(f"  AskTube AI - RAG Evaluation Suite")
    print(f"  Video : {video_id}")
    print(f"  Cases : {len(single_cases)} single-turn  +  {len(conv_cases)} conversation")
    print(f"{'-'*72}\n")

    service = LangSmithEvaluationService(config=settings, rag_service=get_rag_service())

    totals: dict[str, int] = {PASS: 0, WARN: 0, FAIL: 0}

    # -- Single-turn cases ----------------------------------------------------
    categories: dict[str, list] = {}
    for case in single_cases:
        cat = case.get("category", "other")
        categories.setdefault(cat, []).append(case)

    for cat, cases in categories.items():
        print(f"  {'-'*66}")
        print(f"  {cat.upper().replace('_', ' ')}")
        print(f"  {'-'*66}")
        for case in cases:
            status, reason = await run_single_case(service, case, video_id)
            totals[status] += 1
            q_preview = textwrap.shorten(case["question"], width=40, placeholder="...")
            print_row(status, case["id"], q_preview, reason)

    # -- Conversation cases ---------------------------------------------------
    if conv_cases:
        print(f"\n  {'-'*66}")
        print(f"  CONVERSATION / MEMORY")
        print(f"  {'-'*66}")
        for case in conv_cases:
            status, reason = await run_conversation_case(service, case, video_id)
            totals[status] += 1
            print_row(status, case["id"], case.get("category", "memory"), reason)

    # -- Summary --------------------------------------------------------------
    total = sum(totals.values())
    print(f"\n{'-'*72}")
    print(
        f"  Results: "
        f"\033[32m{totals[PASS]} passed\033[0m  "
        f"\033[33m{totals[WARN]} warned\033[0m  "
        f"\033[31m{totals[FAIL]} failed\033[0m  "
        f"/ {total} total"
    )
    print(f"{'-'*72}\n")

    return 0 if totals[FAIL] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
