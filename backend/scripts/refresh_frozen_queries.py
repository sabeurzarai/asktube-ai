#!/usr/bin/env python3
"""
Re-record the frozen search queries in the retrieval evaluation fixture.

The fixture stores, per case, the query _contextualize actually produced
(`search_query`). Measurements that are not about the rewrite search with those
recorded strings instead of calling the model, because the rewrite is a chat
call and its run-to-run variation is larger than the effects a chunk-size or
top_k comparison is trying to detect.

Run this ONLY after deliberately changing the rewrite - the prompt, the chat
model, or _contextualize itself - and then READ THE DIFF before committing. A
rewrite that misreads a question becomes, once frozen, the thing every future
comparison measures. That is not hypothetical: 'show me another one' froze as
'show me another reason to write a function', which misses the passage the case
is about. It was kept deliberately, because a case set in which everything
passes cannot detect a regression - but it was kept KNOWINGLY, which is the
whole point of reading the diff.

First-turn and other no-history cases are left untouched: with nothing to
resolve against there is no rewrite, and their recorded query must stay equal to
the raw question (test_retrieval_eval_fixture.py asserts this).

    cd backend && python scripts/refresh_frozen_queries.py            # show only
    cd backend && python scripts/refresh_frozen_queries.py --write    # persist
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.schemas.rag import ChatMessage
from app.services.conversation_store import InMemoryConversationStore
from app.services.rag_service import RAGService

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "retrieval_eval_cases.json"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="persist the new queries (default: print the diff only)")
    args = parser.parse_args()

    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    service = RAGService(config=settings, vectorstore=None, memory=InMemoryConversationStore())

    changed = 0
    for case in data["cases"]:
        if not case["history"]:
            continue
        history = [ChatMessage(role=t["role"], content=t["content"]) for t in case["history"]]
        rewritten = await service._contextualize(case["question"], history)
        if rewritten == case["search_query"]:
            continue
        changed += 1
        print(f'{case["id"]}\n  alt: {case["search_query"]!r}\n  neu: {rewritten!r}\n')
        case["search_query"] = rewritten

    if not changed:
        print("Keine Aenderung - die eingefrorenen Anfragen entsprechen dem aktuellen Rewrite.")
        return 0

    if args.write:
        FIXTURE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{changed} Anfrage(n) geschrieben. Diff pruefen, bevor committet wird.")
    else:
        print(f"{changed} Anfrage(n) wuerden sich aendern. Mit --write uebernehmen.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
