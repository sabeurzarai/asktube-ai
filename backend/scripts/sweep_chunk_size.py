#!/usr/bin/env python3
"""
AskTube AI CHUNK_MAX_CHARS Sweep
=================================

Re-chunks one video at several CHUNK_MAX_CHARS values and scores each with the
retrieval evaluation cases, so tuning the setting is measured rather than
guessed. Companion to scripts/run_retrieval_eval.py, which measures the CURRENT
setting against the deployed store.

Three things make the comparison honest, and all three are easy to get wrong:

1. NOTHING IS WRITTEN TO THE DEPLOYED DATABASE. Each setting is loaded into a
   fresh InMemoryVectorStore inside this process. Re-ingesting the video five
   times into Postgres would mutate the live demo's data for the duration of
   the sweep and leave whichever setting ran last in place.

2. THE REWRITTEN QUERIES ARE COMPUTED ONCE AND REUSED. _contextualize calls a
   chat model, which is not deterministic. Re-running it per setting would vary
   the query and the chunk size together, and the result would not attribute to
   either.

3. HIT RATE ALONE IS MISLEADING AT LARGE CHUNK SIZES. When a video yields
   fewer than top_k chunks, the search returns the entire video and every case
   "hits" for free. The chunk count is printed next to every row, and a setting
   with chunk_count <= TOP_K is flagged DEGENERATE rather than reported as a
   winner.

A fourth check runs per setting: each case's expect_chunk_containing substring
must still appear in EXACTLY ONE chunk. The fixture picked substrings rather
than chunk ids precisely so re-chunking would not break it - but a substring
that lands in two chunks makes its case pass for the wrong reason, so ambiguity
is reported instead of silently scored.

Prerequisites
-------------
- OPENAI_API_KEY (embeddings for every chunk at every setting, plus one chat
  call per follow-up case for the shared rewrite)
- Network access to YouTube for the transcript. No DATABASE_URL is needed.

Run from the backend/ directory:
    cd backend && python scripts/sweep_chunk_size.py
    cd backend && python scripts/sweep_chunk_size.py --sizes 400,800,1200
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.schemas.rag import ChatMessage
from app.services.chunking_service import build_semantic_chunks
from app.services.conversation_store import InMemoryConversationStore
from app.services.rag_service import RAGService
from app.schemas.transcript import TranscriptResponse
from app.services.transcript_service import TranscriptFetchOptions, get_transcript_service
from app.services.vector_store.memory import InMemoryVectorStore
from app.services.vectorstore_service import VectorStoreService

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "retrieval_eval_cases.json"
DEFAULT_SIZES = [300, 450, 600, 900, 1200, 1600]
TOP_K = 5
OVERLAP_SEGMENTS = 1

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


async def resolve_search_queries(cases: list[dict]) -> list[str]:
    """Contextualize each case once, so every setting searches with the same text."""
    service = RAGService(config=settings, vectorstore=None, memory=InMemoryConversationStore())
    queries = []
    for case in cases:
        history = [ChatMessage(role=t["role"], content=t["content"]) for t in case.get("history", [])]
        queries.append(await service._contextualize(case["question"], history))
    return queries


def substring_occurrences(chunks, needle: str) -> int:
    lowered = needle.lower()
    return sum(1 for c in chunks if lowered in c.text.lower())


async def score_setting(transcript, cases, queries, max_chars: int) -> dict:
    chunks = build_semantic_chunks(
        transcript=transcript,
        max_chunk_chars=max_chars,
        overlap_segments=OVERLAP_SEGMENTS,
    )
    service = VectorStoreService(settings, InMemoryVectorStore())
    await service.upsert_chunks(chunks)

    rows, hits = [], 0
    for case, query in zip(cases, queries, strict=True):
        needle = case["expect_chunk_containing"]
        occurrences = substring_occurrences(chunks, needle)
        results = await service.similarity_search(
            query=query, limit=TOP_K, video_id=transcript.video_id
        )
        rank = next(
            (i for i, r in enumerate(results, start=1) if needle.lower() in r.text.lower()),
            None,
        )
        if rank:
            hits += 1
        best = min((r.distance for r in results if r.distance is not None), default=None)
        rows.append({"name": case["name"], "rank": rank, "distance": best,
                     "occurrences": occurrences})

    lengths = [len(c.text) for c in chunks]
    return {
        "max_chars": max_chars,
        "chunk_count": len(chunks),
        "mean_len": sum(lengths) // len(lengths) if lengths else 0,
        "hits": hits,
        "rows": rows,
        "degenerate": len(chunks) <= TOP_K,
    }


def print_setting(result: dict, total_cases: int) -> None:
    flag = f"  {YELLOW}DEGENERATE - top_k={TOP_K} returns the whole video{RESET}" if result["degenerate"] else ""
    print(f'\nCHUNK_MAX_CHARS={result["max_chars"]:<5} chunks={result["chunk_count"]:<3} '
          f'mittlere Laenge={result["mean_len"]:<5} Treffer={result["hits"]}/{total_cases}{flag}')
    for row in result["rows"]:
        if row["rank"]:
            verdict = f"{GREEN}HIT {RESET} rank={row['rank']}"
        else:
            verdict = f"{RED}MISS{RESET} rank=-"
        distance = f'{row["distance"]:.4f}' if row["distance"] is not None else "-"
        warn = "" if row["occurrences"] == 1 else f'  {YELLOW}<- Substring in {row["occurrences"]} Chunks, nicht eindeutig{RESET}'
        print(f'   {verdict}  dist={distance}  {row["name"][:46]}{warn}')


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", help="comma-separated CHUNK_MAX_CHARS values")
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch the transcript instead of using the cached copy")
    args = parser.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")] if args.sizes else DEFAULT_SIZES

    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    video_id, cases = data["video_id"], data["cases"]

    print(f"\n{'-' * 76}\n  CHUNK_MAX_CHARS Sweep - Video {video_id}, {len(cases)} Faelle, "
          f"top_k={TOP_K}\n{'-' * 76}")

    # Cached on disk: the sweep re-runs often while tuning, and YouTube starts
    # refusing repeated transcript requests (502) well before the tuning is
    # finished. Caching also makes a run reproducible - the same transcript in,
    # the same numbers out - which a measurement tool needs.
    cache = Path(__file__).resolve().parent.parent / "data" / f"transcript_{video_id}.json"
    if cache.exists() and not args.refresh:
        transcript = TranscriptResponse.model_validate_json(cache.read_text(encoding="utf-8"))
        print(f"Transkript aus Cache: {cache}")
    else:
        transcript = await get_transcript_service().get_transcript(
            video_id, TranscriptFetchOptions(language="en")
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(transcript.model_dump_json(), encoding="utf-8")
        print(f"Transkript geholt und gecacht: {cache}")

    print(f"Transkript: {len(transcript.segments)} Segmente, "
          f"{sum(len(s.text) for s in transcript.segments)} Zeichen")

    queries = await resolve_search_queries(cases)
    print("\nSuchanfragen (einmal berechnet, ueber alle Einstellungen konstant):")
    for case, query in zip(cases, queries, strict=True):
        marker = "=" if query == case["question"] else ">"
        print(f'  {marker} {query!r}')

    results = [await score_setting(transcript, cases, queries, size) for size in sizes]
    for result in results:
        print_setting(result, len(cases))

    total_chars = sum(len(s.text) for s in transcript.segments)
    print(f"\n{'-' * 76}\n  Zusammenfassung\n{'-' * 76}")
    print("  Der mittlere Rang ist NICHT ueber Einstellungen hinweg vergleichbar: bei 41")
    print("  Chunks ist Rang 2 eine viel schaerfere Leistung als bei 7. Normiert = Rang")
    print("  geteilt durch Chunk-Anzahl; kleiner ist besser. 'Kontext' ist der Anteil des")
    print("  Videos, den top_k Chunks an das Modell weiterreichen - der eigentliche Preis")
    print("  grober Chunks, unabhaengig vom Fallset messbar.\n")
    print(f'  {"max_chars":<11}{"chunks":<9}{"Treffer":<10}{"Rang":<8}{"normiert":<11}{"Kontext":<10}Hinweis')
    for r in results:
        ranks = [row["rank"] for row in r["rows"] if row["rank"]]
        mean_rank = sum(ranks) / len(ranks) if ranks else None
        rank_display = f"{mean_rank:.2f}" if mean_rank else "-"
        normalized = f"{mean_rank / r['chunk_count']:.3f}" if mean_rank else "-"
        context_share = f"{min(TOP_K, r['chunk_count']) * r['mean_len'] / total_chars:.0%}"
        note = "DEGENERIERT" if r["degenerate"] else ""
        ambiguous = sum(1 for row in r["rows"] if row["occurrences"] != 1)
        if ambiguous:
            note = (note + " " if note else "") + f"{ambiguous} Substring(s) mehrdeutig"
        print(f'  {r["max_chars"]:<11}{r["chunk_count"]:<9}{r["hits"]}/{len(cases):<8}'
              f'{rank_display:<8}{normalized:<11}{context_share:<10}{note}')
    print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
