#!/usr/bin/env python3
"""
AskTube AI CHUNK_MAX_CHARS Sweep
=================================

Re-chunks the evaluation videos at several CHUNK_MAX_CHARS values and scores the
retrieval cases against each, so tuning the setting is measured rather than
guessed. Companion to scripts/run_retrieval_eval.py, which measures the CURRENT
setting against the deployed store.

Four things make the comparison honest, and all four are easy to get wrong:

1. NOTHING IS WRITTEN TO THE DEPLOYED DATABASE. Each video at each setting is
   loaded into a fresh InMemoryVectorStore inside this process. Re-ingesting
   into Postgres would mutate the live demo's data for the duration of the
   sweep and leave whichever setting ran last in place. Verified faithful: at
   1200 this reproduced the pgvector numbers to within float noise.

2. THE QUERIES ARE THE FIXTURE'S FROZEN REWRITES, not live ones. The rewrite is
   a chat call and is not deterministic. Two runs of this sweep with identical
   transcripts and identical, deterministic chunking once disagreed by a whole
   case for that reason alone. Frozen, consecutive runs are bit-identical.

3. HIT RATE ALONE IS MISLEADING AT LARGE CHUNK SIZES. When a video yields fewer
   than top_k chunks, the search returns the entire video and every case "hits"
   for free. Chunk counts are printed per video and a degenerate setting is
   flagged rather than reported as a winner. Raw mean rank is not comparable
   across settings either - rank 2 among 41 chunks is a far sharper result than
   rank 2 among 7 - so a normalised rank is reported beside it.

4. TRANSCRIPTS COME FROM tests/fixtures, NOT FROM YOUTUBE. They are committed,
   so a sweep is reproducible, needs no network, and cannot drift because a
   caption track changed between runs.

Cost: embeddings for every chunk of every video at every setting. No chat calls.

    cd backend && python scripts/sweep_chunk_size.py
    cd backend && python scripts/sweep_chunk_size.py --sizes 450,600,900
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.schemas.transcript import TranscriptResponse
from app.services.chunking_service import build_semantic_chunks
from app.services.vector_store.memory import InMemoryVectorStore
from app.services.vectorstore_service import VectorStoreService

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FIXTURE_PATH = FIXTURES / "retrieval_eval_cases.json"
DEFAULT_SIZES = [450, 600, 900, 1200]
TOP_K = 5
OVERLAP_SEGMENTS = 1

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def substring_occurrences(chunks, needle: str) -> int:
    lowered = needle.lower()
    return sum(1 for c in chunks if lowered in c.text.lower())


async def score_setting(transcripts: dict, cases: list[dict], max_chars: int) -> dict:
    """Score every case at one chunk size, each against its own video's store."""
    chunks_by_video, stores = {}, {}
    for video_id, transcript in transcripts.items():
        chunks = build_semantic_chunks(
            transcript=transcript, max_chunk_chars=max_chars, overlap_segments=OVERLAP_SEGMENTS
        )
        chunks_by_video[video_id] = chunks
        service = VectorStoreService(settings, InMemoryVectorStore())
        await service.upsert_chunks(chunks)
        stores[video_id] = service

    rows, hits = [], 0
    for case in cases:
        video_id = case["video_id"]
        results = await stores[video_id].similarity_search(
            query=case["search_query"], limit=TOP_K, video_id=video_id
        )
        best = min((r.distance for r in results if r.distance is not None), default=None)

        if case["kind"] == "off_topic":
            # Inverted: nothing in the video answers this, so a LOW distance is
            # the failure. Chunk size shifts these too - finer chunks can raise
            # a spurious similarity - so they belong in the sweep, not beside it.
            passed = best is not None and best > case["expect_distance_above"]
            hits += bool(passed)
            rows.append({"id": case["id"], "video_id": video_id, "kind": case["kind"],
                         "rank": None, "distance": best, "occurrences": 1, "passed": passed})
            continue

        needle = case["expect_chunk_containing"]
        rank = next(
            (i for i, r in enumerate(results, start=1) if needle.lower() in r.text.lower()), None
        )
        if rank:
            hits += 1
        rows.append({"id": case["id"], "video_id": video_id, "kind": case["kind"], "rank": rank,
                     "distance": best,
                     "occurrences": substring_occurrences(chunks_by_video[video_id], needle),
                     "passed": rank is not None})

    per_video = {}
    for video_id, chunks in chunks_by_video.items():
        lengths = [len(c.text) for c in chunks]
        total = sum(len(s.text) for s in transcripts[video_id].segments)
        mean_len = sum(lengths) // len(lengths) if lengths else 0
        per_video[video_id] = {
            "chunk_count": len(chunks),
            "mean_len": mean_len,
            "context_share": min(TOP_K, len(chunks)) * mean_len / total if total else 0,
            "degenerate": len(chunks) <= TOP_K,
        }

    return {"max_chars": max_chars, "hits": hits, "rows": rows, "per_video": per_video}


def print_setting(result: dict, total_cases: int) -> None:
    parts = []
    for video_id, v in result["per_video"].items():
        flag = f" {YELLOW}DEGENERIERT{RESET}" if v["degenerate"] else ""
        parts.append(f'{video_id}: {v["chunk_count"]} Chunks, Kontext {v["context_share"]:.0%}{flag}')
    print(f'\nCHUNK_MAX_CHARS={result["max_chars"]:<5} bestanden={result["hits"]}/{total_cases}   '
          + " | ".join(parts))
    for row in result["rows"]:
        if row["passed"]:
            continue
        marker = "Distanz" if row["kind"] == "off_topic" else f'rank={row["rank"] or "-"}'
        distance = f'{row["distance"]:.4f}' if row["distance"] is not None else "-"
        warn = "" if row["occurrences"] == 1 else f'  {YELLOW}Substring in {row["occurrences"]} Chunks{RESET}'
        print(f'   {RED}FAIL{RESET} {row["id"]:<24} {marker:<9} dist={distance}{warn}')


async def main() -> int:
    parser = argparse.ArgumentParser(description="Compare CHUNK_MAX_CHARS values on the eval set.")
    parser.add_argument("--sizes", help="comma-separated CHUNK_MAX_CHARS values")
    args = parser.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")] if args.sizes else DEFAULT_SIZES

    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]
    transcripts = {
        video_id: TranscriptResponse.model_validate_json(
            (FIXTURES / meta["transcript_fixture"]).read_text(encoding="utf-8")
        )
        for video_id, meta in data["videos"].items()
    }

    print(f"\n{'-' * 78}\n  CHUNK_MAX_CHARS Sweep - {len(cases)} Faelle ueber "
          f"{len(transcripts)} Videos, top_k={TOP_K}\n{'-' * 78}")
    for video_id, transcript in transcripts.items():
        chars = sum(len(s.text) for s in transcript.segments)
        n = sum(1 for c in cases if c["video_id"] == video_id)
        print(f'  {video_id}  {chars:>6} Zeichen  {n:>2} Faelle  {data["videos"][video_id]["title"][:44]}')
    print("  Nur nicht bestandene Faelle werden einzeln aufgefuehrt.")

    results = [await score_setting(transcripts, cases, size) for size in sizes]
    for result in results:
        print_setting(result, len(cases))

    print(f"\n{'-' * 78}\n  Zusammenfassung\n{'-' * 78}")
    print("  Normierter Rang = mittlerer Rang / Chunk-Anzahl; kleiner ist besser. Roher Rang")
    print("  ist NICHT ueber Einstellungen vergleichbar. 'Kontext' ist der Anteil eines Videos,")
    print("  den top_k Chunks an das Modell weiterreichen - der Preis grober Chunks, unabhaengig")
    print("  vom Fallset messbar.\n")
    header = f'  {"max_chars":<11}{"bestanden":<12}{"Rang":<8}{"normiert":<11}Kontext je Video'
    print(header)
    for r in results:
        ranks = [row["rank"] for row in r["rows"] if row["rank"]]
        mean_rank = sum(ranks) / len(ranks) if ranks else None
        mean_chunks = sum(v["chunk_count"] for v in r["per_video"].values()) / len(r["per_video"])
        normalized = f"{mean_rank / mean_chunks:.3f}" if mean_rank else "-"
        shares = "  ".join(f'{vid[:6]}={v["context_share"]:.0%}' for vid, v in r["per_video"].items())
        print(f'  {r["max_chars"]:<11}{f"{r["hits"]}/{len(cases)}":<12}'
              f'{f"{mean_rank:.2f}" if mean_rank else "-":<8}{normalized:<11}{shares}')
    print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
