#!/usr/bin/env python3
"""
AskTube AI Retrieval Evaluation Runner
========================================

Scores whether retrieval surfaces the expected passage, per conversation case in
tests/fixtures/retrieval_eval_cases.json, against the DEPLOYED vector store.

Two modes, and picking the wrong one makes the numbers meaningless:

  live (default)  Runs the real pipeline through RAGService.prepare_context, so
                  the rewrite step is exercised exactly as production runs it.
                  Use this to judge RETRIEVAL AS A WHOLE. Costs one chat call
                  per case with history, and is not reproducible run to run.

  --frozen        Searches with the search_query recorded in the fixture instead
                  of calling the rewrite. Deterministic and free of chat calls.
                  Use this whenever you are changing something OTHER than the
                  rewrite - chunk size, top_k, the embedding model - because the
                  rewrite's run-to-run variation is larger than the effects those
                  changes produce, and it will drown them.

Case kinds
----------
first_turn          No history, so no rewrite. Regression guards: if these move,
                    a change has touched queries it should have left alone.
followup_reference  A pronoun or ellipsis that the history can resolve.
followup_vague      Under-specified. Read the query it SEARCHED WITH, not just
                    the verdict - a rewrite that invents a topic can still hit.
topic_shift         Self-contained and unrelated to the history. Guards the
                    opposite failure: a rewrite dragging stale context in.
off_topic           Nothing in the video answers it. Scored INVERTED: passing
                    means the best distance stayed ABOVE the threshold. Without
                    these the set cannot detect a system that returns confident
                    garbage, since every other case rewards returning something.

Prerequisites
-------------
1. EVERY video listed under "videos" in the fixture already ingested in the
   deployed store. A missing one does not error - its cases simply return
   nothing and read as retrieval failures, so check before blaming the code.
2. DATABASE_URL set (the vector store backend reads it via settings).
3. OPENAI_API_KEY set (embeddings always; chat too unless --frozen).

    cd backend && python scripts/run_retrieval_eval.py
    cd backend && python scripts/run_retrieval_eval.py --frozen
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.services.conversation_store import InMemoryConversationStore
from app.services.rag_service import RAGService
from app.services.vectorstore_service import get_vectorstore_service

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "retrieval_eval_cases.json"
TOP_K = 5

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

KIND_ORDER = ["first_turn", "followup_reference", "followup_vague", "topic_shift", "off_topic"]
KIND_TITLE = {
    "first_turn": "Erst-Fragen (Regressionswaechter, kein Rewrite)",
    "followup_reference": "Folgefragen mit aufloesbarem Bezug",
    "followup_vague": "Vage Folgefragen (Halluzinationsrisiko)",
    "topic_shift": "Themenwechsel (Rewrite darf NICHT verankern)",
    "off_topic": "Nicht im Video (invertiert: Distanz muss HOCH bleiben)",
}


async def build_seeded_store(case: dict) -> tuple[InMemoryConversationStore, str]:
    """Seed a conversation without replaying it through the LLM.

    append_exchange takes both halves of a pair at once; the fixture test
    guarantees the history is paired, so stepping by 2 cannot drop a turn.
    """
    store = InMemoryConversationStore()
    session_id = store.create_session_id()
    history = case.get("history", [])
    for i in range(0, len(history) - 1, 2):
        await store.append_exchange(session_id, history[i]["content"], history[i + 1]["content"])
    return store, session_id


async def run_case(case: dict, frozen: bool) -> dict:
    vectorstore = get_vectorstore_service()
    video_id = case["video_id"]

    if frozen:
        query = case["search_query"]
        results = await vectorstore.similarity_search(
            query=query, limit=TOP_K, video_id=video_id
        )
    else:
        store, session_id = await build_seeded_store(case)
        service = RAGService(config=settings, vectorstore=vectorstore, memory=store)
        query_seen = {}
        inner = service._contextualize

        async def recording(msg, hist):  # noqa: ANN001, ANN202
            result = await inner(msg, hist)
            query_seen["query"] = result
            return result

        service._contextualize = recording
        _, results, _ = await service.prepare_context(
            message=case["question"], video_id=video_id, session_id=session_id, top_k=TOP_K
        )
        query = query_seen.get("query", case["question"])

    best = min((r.distance for r in results if r.distance is not None), default=None)

    if case["kind"] == "off_topic":
        # Inverted: nothing should match well. A LOW distance is the failure.
        passed = best is not None and best > case["expect_distance_above"]
        return {"case": case, "passed": passed, "rank": None, "best": best, "query": query}

    needle = case["expect_chunk_containing"].lower()
    rank = next((i for i, r in enumerate(results, start=1) if needle in r.text.lower()), None)
    return {"case": case, "passed": rank is not None, "rank": rank, "best": best, "query": query}


def print_row(row: dict) -> None:
    case = row["case"]
    verdict = f"{GREEN}PASS{RESET}" if row["passed"] else f"{RED}FAIL{RESET}"
    if case["kind"] == "off_topic":
        detail = f'beste Distanz={row["best"]:.4f} (muss >{case["expect_distance_above"]})'
    else:
        rank = row["rank"] if row["rank"] else "-"
        detail = f'rank={rank:<3} beste Distanz={row["best"]:.4f}' if row["best"] is not None else f"rank={rank}"
    print(f'  {verdict}  {case["id"]:<24} {case["video_id"][:6]}  {detail}')
    if row["query"] != case["question"]:
        print(f'{DIM}         gesucht mit: {row["query"]!r}{RESET}')


async def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieval evaluation against the deployed store.")
    parser.add_argument("--frozen", action="store_true",
                        help="search with the fixture's recorded queries instead of calling the rewrite")
    args = parser.parse_args()

    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]

    mode = "FROZEN (deterministisch, kein Chat-Aufruf)" if args.frozen else "LIVE (Rewrite wird ausgefuehrt)"
    print(f"\n{'-' * 76}\n  AskTube AI - Retrieval Evaluation\n"
          f"  Faelle: {len(cases)}   Modus: {mode}\n{'-' * 76}")
    for video_id, meta in data["videos"].items():
        count = sum(1 for c in cases if c["video_id"] == video_id)
        print(f'  {video_id}  {count:>2} Faelle  {meta["title"][:48]}')
    print("  Beide Videos muessen im eingesetzten Store ingestiert sein.")

    rows = [await run_case(c, args.frozen) for c in cases]

    for kind in KIND_ORDER:
        group = [r for r in rows if r["case"]["kind"] == kind]
        if not group:
            continue
        passed = sum(1 for r in group if r["passed"])
        print(f'\n{KIND_TITLE[kind]}  [{passed}/{len(group)}]')
        for row in group:
            print_row(row)

    total = sum(1 for r in rows if r["passed"])
    ranked = [r["rank"] for r in rows if r["rank"]]
    print(f"\n{'-' * 76}")
    print(f"  Bestanden: {total}/{len(rows)}"
          + (f"   mittlerer Rang der Treffer: {sum(ranked) / len(ranked):.2f}" if ranked else ""))
    if not args.frozen:
        print(f"  {YELLOW}Live-Modus: die Umformulierung ist nicht deterministisch. Fuer Vergleiche,"
              f"\n  bei denen NICHT der Rewrite die Variable ist, --frozen verwenden.{RESET}")
    print(f"{'-' * 76}\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
