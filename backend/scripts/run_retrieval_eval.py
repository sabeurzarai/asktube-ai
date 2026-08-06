#!/usr/bin/env python3
"""
AskTube AI Retrieval Evaluation Runner
========================================

Loads evaluation cases from tests/fixtures/retrieval_eval_cases.json and runs
each one directly through RAGService.prepare_context, then reports whether
retrieval surfaced the expected chunk.

This measures retrieval in isolation: the search runs exactly as production
does, but no LLM call generates an answer. Each case's conversation history is
seeded synthetically via InMemoryConversationStore.append_exchange, so seeding
costs nothing and introduces no model variance.

Note that "no LLM call" is not quite true for cases WITH history: since
prepare_context contextualizes follow-up questions, those cases make one chat
call to rewrite the query. That call is the thing being measured, and its
result is printed as "rewritten:" beneath the case so a rewrite that invented
a topic is visible rather than hidden behind a hit rate.

It exists to compare hit rates before and after a change to how questions are
embedded. It is deliberately not part of the automated test suite - it costs
money (OpenAI embeddings, plus one chat call per follow-up case) and depends
on state that only exists after manual ingestion.

Prerequisites
-------------
1. Video fWjsdhR3z3c must already be ingested in the vector store:
       curl -X POST http://localhost:8000/api/videos/fWjsdhR3z3c/ingest
   (or use the frontend processing flow)

2. DATABASE_URL must be set (the vector store backend reads it via settings).

3. OPENAI_API_KEY must be set in backend/.env (required for embeddings).

4. Run from the backend/ directory:
       cd backend
       python scripts/run_retrieval_eval.py

Interpreting results
---------------------
Each case prints one of:
  HIT   - a returned chunk's text contains expect_chunk_containing
  MISS  - no returned chunk contains it

Alongside the verdict: the 1-based rank of the matching chunk (or "-" on a
miss) and the best (lowest) distance among the returned chunks. A final
"N/M" hit-rate line summarizes the run.

Exit code 0 always - this is a measurement tool, not a pass/fail gate.
"""

import asyncio
import json
import sys
import textwrap
from pathlib import Path

# Allow running from backend/ without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.services.conversation_store import InMemoryConversationStore
from app.services.rag_service import RAGService
from app.services.vectorstore_service import get_vectorstore_service

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "retrieval_eval_cases.json"
TOP_K = 5

HIT = "HIT "
MISS = "MISS"


# ---------------------------------------------------------------------------
# Single-case evaluation
# ---------------------------------------------------------------------------

async def run_single_case(case: dict, video_id: str) -> tuple[str, str, float | None, str | None]:
    """Run one retrieval case.

    Returns (status, rank_display, best_distance, rewritten_query), where the
    last item is None when the question was searched for unchanged.
    """
    history = case.get("history", [])
    question = case["question"]
    expect_chunk_containing = case["expect_chunk_containing"]

    store = InMemoryConversationStore()
    session_id = store.create_session_id()

    # history is a flat list of {"role", "content"} in user/assistant pairs;
    # append_exchange takes both halves of a pair at once, so walk in steps of 2.
    for i in range(0, len(history) - 1, 2):
        user_turn = history[i]
        assistant_turn = history[i + 1]
        await store.append_exchange(session_id, user_turn["content"], assistant_turn["content"])

    service = RAGService(config=settings, vectorstore=get_vectorstore_service(), memory=store)

    # Observe the rewrite without altering it: the real method still runs and its
    # result is what retrieval uses. A rewrite that invents a topic the
    # conversation never mentioned is the main risk of this feature, and it would
    # be invisible in a hit rate alone.
    rewritten: str | None = None
    inner_contextualize = service._contextualize

    async def recording_contextualize(msg, hist):  # noqa: ANN001, ANN202
        nonlocal rewritten
        result = await inner_contextualize(msg, hist)
        rewritten = result if result != msg else None
        return result

    service._contextualize = recording_contextualize

    _, retrieved_context, _history = await service.prepare_context(
        message=question,
        video_id=video_id,
        session_id=session_id,
        top_k=TOP_K,
    )

    best_distance = min(
        (r.distance for r in retrieved_context if r.distance is not None),
        default=None,
    )

    # Case-insensitive, matching how Task 1 verified expect_chunk_containing
    # was unique across the video's chunks.
    needle = expect_chunk_containing.lower()
    for rank, result in enumerate(retrieved_context, start=1):
        if needle in result.text.lower():
            return HIT, str(rank), best_distance, rewritten

    return MISS, "-", best_distance, rewritten


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

STATUS_COLOR = {HIT: "\033[32m", MISS: "\033[31m"}
RESET = "\033[0m"


def print_row(
    status: str, name: str, rank: str, distance: float | None, rewritten: str | None = None
) -> None:
    color = STATUS_COLOR[status]
    label = f"{color}{status}{RESET}"
    distance_display = f"{distance:.4f}" if distance is not None else "-"
    name_preview = textwrap.shorten(name, width=48, placeholder="...")
    print(f"  {label}  rank={rank:<3}  distance={distance_display:<8}  {name_preview}")
    if rewritten:
        print(f"          searched for: {rewritten!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> int:
    with FIXTURE_PATH.open() as f:
        data = json.load(f)

    video_id: str = data["video_id"]
    cases: list[dict] = data.get("cases", [])

    print(f"\n{'-'*72}")
    print(f"  AskTube AI - Retrieval Evaluation")
    print(f"  Video : {video_id}")
    print(f"  Cases : {len(cases)}")
    print(f"{'-'*72}\n")

    hits = 0
    for case in cases:
        status, rank, distance, rewritten = await run_single_case(case, video_id)
        if status == HIT:
            hits += 1
        print_row(status, case["name"], rank, distance, rewritten)

    total = len(cases)
    print(f"\n{'-'*72}")
    print(f"  Hit rate: {hits}/{total}")
    print(f"{'-'*72}\n")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
