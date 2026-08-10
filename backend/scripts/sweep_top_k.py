#!/usr/bin/env python3
"""
AskTube AI top_k Sweep
=======================

Answers one question: what is the SMALLEST top_k that keeps the recall we
already have?

That framing is deliberate, because the obvious one is unanswerable. Hit rate is
MONOTONE NON-DECREASING in top_k - a case passes when the expected chunk is
among the first k, so a larger k can never lose a hit. At k = the chunk count
every case passes trivially. "Higher scored better" is therefore not a finding,
it is arithmetic, and a sweep that reports only hit rate would recommend the
largest k every time.

What top_k actually trades is recall against the share of the transcript handed
to the model. That share scales linearly with k, and it is the same cost that
drove CHUNK_MAX_CHARS down from 1200 to 600: a prompt that promises to answer
only from the provided context means less when the context is most of the video.

So the useful signal is the RANK DISTRIBUTION of the hits. If every case that
hits does so at rank <= 3, then k=5 is buying nothing but context, and k=3 keeps
identical recall at 40% less context. Where the curve goes flat is where k
should sit.

Two things this sweep deliberately does not do:

- It does not score off_topic cases. Their metric is the BEST (minimum) distance
  among the results, which does not change with k at all - the closest match is
  the closest match whether you return 1 result or 10. Including them would pad
  every row with four free passes and flatten the very curve being read.

- It does not touch the deployed database. Both videos are chunked in-process at
  the configured CHUNK_MAX_CHARS and loaded into InMemoryVectorStore.

Implementation note: each case is queried ONCE at a large k, and hit@k is then
derived from the rank. That is exactly equivalent to re-querying per k, and it
costs one embedding per case instead of one per case per k.

    cd backend && python scripts/sweep_top_k.py
    cd backend && python scripts/sweep_top_k.py --max-k 12
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
OVERLAP_SEGMENTS = 1
CURRENT_TOP_K = 5

GREEN, RED, YELLOW, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"


async def rank_every_case(
    transcripts: dict, cases: list[dict], max_k: int
) -> tuple[list[dict], dict]:
    """Return each content case's rank, or None if it is not in the top max_k.

    The second element is the per-video chunk statistics the report needs to
    compute context share; the annotation used to claim only the rows.
    """
    stores, stats = {}, {}
    for video_id, transcript in transcripts.items():
        chunks = build_semantic_chunks(
            transcript=transcript,
            max_chunk_chars=settings.chunk_max_chars,
            overlap_segments=OVERLAP_SEGMENTS,
        )
        service = VectorStoreService(settings, InMemoryVectorStore())
        await service.upsert_chunks(chunks)
        stores[video_id] = service
        lengths = [len(c.text) for c in chunks]
        stats[video_id] = {
            "chunk_count": len(chunks),
            "mean_len": sum(lengths) // len(lengths) if lengths else 0,
            "total_chars": sum(len(s.text) for s in transcript.segments),
        }

    rows = []
    for case in cases:
        if case["kind"] == "off_topic":
            continue
        video_id = case["video_id"]
        results = await stores[video_id].similarity_search(
            query=case["search_query"], limit=max_k, video_id=video_id
        )
        needle = case["expect_chunk_containing"].lower()
        rank = next(
            (i for i, r in enumerate(results, start=1) if needle in r.text.lower()), None
        )
        rows.append({"id": case["id"], "kind": case["kind"], "video_id": video_id, "rank": rank})
    return rows, stats


def main_report(rows: list[dict], stats: dict, max_k: int) -> None:
    total = len(rows)
    ceiling = sum(1 for r in rows if r["rank"] is not None)

    print(f"\n{'-' * 78}\n  Trefferquote je top_k  ({total} inhaltliche Faelle, "
          f"off_topic ausgeschlossen)\n{'-' * 78}")
    print("  Die Quote kann mit k nur steigen. Interessant ist, wo sie flach wird -")
    print("  jedes k darueber kauft nur noch Kontext.\n")
    print(f'  {"k":<5}{"Treffer":<12}{"neu":<7}{"Kontextanteil je Video":<26}Hinweis')

    plateau_at = None
    for k in range(1, max_k + 1):
        newly = [r["id"] for r in rows if r["rank"] == k]
        hits = sum(1 for r in rows if r["rank"] is not None and r["rank"] <= k)
        shares = "  ".join(
            f'{vid[:6]}={min(k, s["chunk_count"]) * s["mean_len"] / s["total_chars"]:.0%}'
            for vid, s in stats.items()
        )
        note = ""
        if hits == ceiling and plateau_at is None:
            plateau_at = k
            note = f"{GREEN}Plateau{RESET}"
        if k == CURRENT_TOP_K:
            note = (note + " " if note else "") + f"{BOLD}<- aktuell{RESET}"
        marker = f"+{len(newly)}" if newly else "."
        print(f"  {k:<5}{f'{hits}/{total}':<10}{marker:<6}{shares:<26}{note}")
        if newly:
            # Which cases a given k buys is the whole decision: one more case is
            # worth 6 points of context only if that case is sound.
            print(f'       {", ".join(newly)}')

    print(f"\n{'-' * 78}")
    if plateau_at is None:
        print(f"  Kein Plateau bis k={max_k}: {ceiling}/{total} Faelle sind ueberhaupt auffindbar.")
    else:
        current_hits = sum(1 for r in rows if r["rank"] is not None and r["rank"] <= CURRENT_TOP_K)
        print(f"  Kleinstes k mit voller Trefferquote ({ceiling}/{total}): {BOLD}{plateau_at}{RESET}")
        print(f"  Aktuell k={CURRENT_TOP_K} -> {current_hits}/{total}.")
        if plateau_at < CURRENT_TOP_K:
            saved = (CURRENT_TOP_K - plateau_at) / CURRENT_TOP_K
            print(f"  k={plateau_at} haelt dieselbe Trefferquote bei {saved:.0%} weniger Kontext.")
        elif plateau_at > CURRENT_TOP_K:
            print(f"  Das aktuelle k liegt UNTER dem Plateau - Erhoehen wuerde Faelle gewinnen.")

    missed = [r for r in rows if r["rank"] is None]
    if missed:
        print(f"\n  Bis k={max_k} gar nicht gefunden ({len(missed)}) - kein k behebt das:")
        for r in missed:
            print(f'    {RED}{r["id"]}{RESET} ({r["video_id"][:6]}, {r["kind"]})')

    beyond = [r for r in rows if r["rank"] and r["rank"] > CURRENT_TOP_K]
    if beyond:
        print(f"\n  Erst jenseits des aktuellen k={CURRENT_TOP_K} gefunden:")
        for r in sorted(beyond, key=lambda x: x["rank"]):
            print(f'    {YELLOW}{r["id"]}{RESET} bei Rang {r["rank"]}')
    print()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Find the smallest top_k that keeps recall.")
    parser.add_argument("--max-k", type=int, default=10, help="largest k to examine (default 10)")
    args = parser.parse_args()

    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    transcripts = {
        video_id: TranscriptResponse.model_validate_json(
            (FIXTURES / meta["transcript_fixture"]).read_text(encoding="utf-8")
        )
        for video_id, meta in data["videos"].items()
    }

    print(f"\n{'-' * 78}\n  top_k Sweep - CHUNK_MAX_CHARS={settings.chunk_max_chars}, "
          f"{len(transcripts)} Videos\n{'-' * 78}")

    rows, stats = await rank_every_case(transcripts, data["cases"], args.max_k)
    for video_id, s in stats.items():
        print(f'  {video_id}  {s["chunk_count"]:>3} Chunks, mittlere Laenge {s["mean_len"]}')
    main_report(rows, stats, args.max_k)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
