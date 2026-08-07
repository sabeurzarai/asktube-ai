# Summarisation Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer broad questions ("what is this video about?") from the whole transcript instead of five arbitrary chunks, with verifiable timestamps.

**Architecture:** A pure heuristic classifies the question with no model call. When it fires, `RAGService` reads every chunk of the video through a new `VectorStore` method, rebuilds a timestamped transcript, and makes one chat call. Timestamps in the answer are validated against the real chunks before becoming citations. Any failure falls through to today's retrieval path.

**Tech Stack:** FastAPI, LangChain, pgvector, pytest / pytest-asyncio in `auto` mode.

## Global Constraints

- Deployment stays at **$0/month**.
- **No ordinary question may change behaviour.** This is the primary constraint. The 26 content cases in `retrieval_eval_cases.json` must all classify as not-broad.
- **No additional model call on a question that is not broad.** Follow-ups keep the single rewrite call they make today.
- The heuristic is a **pure function**: no I/O, no model, no `async`.
- **The summarisation path degrades, it does not fail.** Every failure falls through to the existing retrieval path.
- Length budget: **40,000 characters** of rebuilt transcript. Above it, fall through.
- Public API contract and response schema unchanged. Frontend untouched: `cd frontend && npx tsc --noEmit && npm test` → **79 passed**.
- Baseline before this plan: `cd backend && OPENAI_API_KEY=dummy python -m pytest -q` → **221 passed, 1 skipped**. Report actual counts at every step.
- Run the suite from `backend/`, never the repo root.
- Work on branch `quality/contextualized-retrieval`. Do not push to `main`.

## A correction to the spec, made here rather than discovered later

The spec says the rebuilt transcript "must deduplicate using `segment_indices` or
the boundary segment appears twice". **That is not fully achievable and the plan
does not pretend otherwise.**

`TranscriptChunk` stores its text as one concatenated string plus a list of
segment indices. It does not store per-segment text. So when chunk N covers
segments 10–20 and chunk N+1 covers 20–30, segment 20's *words* appear in both
strings and cannot be removed without the original segments.

What this plan does instead:

- Drop any chunk whose segments are **entirely** already seen (protects against
  true duplicates, e.g. a re-ingest artefact).
- Accept the one-segment overlap at each boundary — roughly 2% of the text,
  a few repeated words per boundary, immaterial to a summary.

`rebuild_transcript`'s docstring states this so no one later reads the spec,
believes dedup is complete, and builds on that belief.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/question_kind.py` | **new** — `is_broad_question`, pure |
| `backend/app/services/summary.py` | **new** — prompt, transcript rebuild, timestamp parsing/validation, all pure except the prompt constant |
| `backend/app/services/vector_store/base.py` | add `list_video_chunks` to the protocol |
| `backend/app/services/vector_store/memory.py` | implement it |
| `backend/app/services/vector_store/postgres.py` | implement it |
| `backend/app/services/vectorstore_service.py` | pass it through |
| `backend/app/services/rag_service.py` | `summarize_video` orchestration + the branch |
| `backend/tests/test_question_kind.py` | **new** |
| `backend/tests/test_summary.py` | **new** |
| `backend/tests/test_vector_store_contract.py` | contract tests for the new method |
| `backend/tests/test_retrieval_eval_fixture.py` | the 26-case not-broad guard |
| `backend/tests/test_rag_service.py` | branch + degradation tests |

The pure parts live outside `rag_service.py` deliberately: that file is already
~470 lines and owns orchestration. Transcript rebuilding and timestamp
validation are pure functions with no service dependencies, and putting them in
their own module makes them testable without constructing a `RAGService`.

---

### Task 1: The broad-question heuristic

**Files:**
- Create: `backend/app/services/question_kind.py`
- Test: `backend/tests/test_question_kind.py`
- Test: `backend/tests/test_retrieval_eval_fixture.py` (add one test)

**Interfaces:**
- Produces: `is_broad_question(message: str) -> bool`. Pure, synchronous, no I/O.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_question_kind.py`:

```python
"""The broad-question heuristic.

A pure function, so these tests need no database, no key and no event loop.
That is the point: an LLM classifier here would be non-deterministic, would add
latency to every request, and would break the documented guarantee that a first
turn makes no model call.
"""

import json
from pathlib import Path

import pytest

from app.services.question_kind import is_broad_question

BROAD = [
    "What is this video about?",
    "what's this video about",
    "What is it about?",
    "Summarize this video",
    "summarise the video",
    "Give me a summary",
    "give me a short overview of this video",
    "What are the main points?",
    "What does this video cover?",
    "tldr",
    # German - the app is used in German, so coverage is a decision, not an accident.
    "Worum geht es in dem Video?",
    "worum geht's",
    "Was behandelt dieses Video?",
    "Gib mir eine kurze Zusammenfassung",
    "Fasse das Video zusammen",
    "Gib mir einen Überblick",
]

NARROW = [
    "How do I do addition in Python?",
    "What does the video say about loops?",
    "give me an example of one",
    "What is the pass keyword for?",
    "and the next one?",
    "What is a vascular plant?",
    # The dangerous near-miss: contains "about" and names the video, but asks
    # about one topic. Matching this would send a passage question down the
    # summary path.
    "What is this video about loops?",
    "Summarize what the video says about the while loop",
]


@pytest.mark.parametrize("message", BROAD)
def test_broad_questions_are_recognised(message: str) -> None:
    assert is_broad_question(message) is True


@pytest.mark.parametrize("message", NARROW)
def test_narrow_questions_are_not_broad(message: str) -> None:
    assert is_broad_question(message) is False


def test_empty_and_whitespace_are_not_broad() -> None:
    assert is_broad_question("") is False
    assert is_broad_question("   ") is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_question_kind.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.question_kind'`.

- [ ] **Step 3: Implement**

Create `backend/app/services/question_kind.py`:

```python
"""Classifying a question as broad, without a model call.

A broad question asks about the whole video ("what is this video about?") rather
than a passage. Top-k retrieval answers those badly by construction, so they take
a different path.

This is a pure pattern match on purpose. An LLM classifier would be
non-deterministic, would add a call to every request including first turns - which
are documented and tested to make no model call - and would put a new failure
source on the answer path. The cost is that only phrasings someone thought of are
recognised; anything else falls through to the retrieval path, which is exactly
today's behaviour, so a miss is never a regression.
"""

import re

# fullmatch, not search: "what is this video about loops" is a PASSAGE question
# and must not be caught by the "what is this video about" pattern. Requiring the
# whole message to match is what separates the two, and it holds because broad
# questions are short by nature.
_BROAD_PATTERNS = [
    r"what(?:'s| is| are) (?:this |the )?video about",
    r"what(?:'s| is) it about",
    r"what (?:is|are) the (?:main |key )?(?:points?|topics?|takeaways?)",
    r"what does (?:this |the )?video (?:cover|discuss|talk about)",
    r"(?:can you )?(?:give me |tell me )?(?:a |an )?(?:short |brief |quick )?"
    r"(?:summary|overview)(?: of (?:this |the )?video)?",
    r"summari[sz]e(?: (?:this|the) video)?",
    r"tl ?dr",
    # German
    r"wor(?:um|ueber|über) geht(?:'s| es)(?: (?:in dem|im|in diesem) video)?",
    r"was behandelt (?:das|dieses) video",
    r"(?:gib mir )?(?:eine )?(?:kurze )?zusammenfassung(?: (?:des|vom) videos?)?",
    r"fass(?:e)? (?:das|dieses) video zusammen",
    r"(?:gib mir )?(?:einen )?(?:kurzen )?(?:ueberblick|überblick)(?: ueber das video| über das video)?",
    r"was sind die (?:haupt)?(?:themen|punkte)",
]

_COMPILED = [re.compile(pattern) for pattern in _BROAD_PATTERNS]


def _normalise(message: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    Apostrophes survive so "what's" stays one token; umlauts survive so the
    German patterns match without the caller transliterating.
    """
    lowered = message.lower().strip()
    cleaned = re.sub(r"[^a-z0-9äöüß' ]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_broad_question(message: str) -> bool:
    """True when the message asks about the video as a whole."""
    normalised = _normalise(message)
    if not normalised:
        return False

    return any(pattern.fullmatch(normalised) for pattern in _COMPILED)
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_question_kind.py -q
```
Expected: PASS — 25 tests (16 broad + 8 narrow + 1 empty).

If a NARROW case fails, do NOT loosen the test. Tighten the pattern: a false
positive here is the exact risk this feature was warned about.

- [ ] **Step 5: Add the fixture-corpus guard**

Append to `backend/tests/test_retrieval_eval_fixture.py`:

```python
def test_no_content_case_is_classified_as_broad(fixture_data) -> None:  # noqa: ANN001
    """The regression guard for the summarisation path's one real risk.

    These 26 questions were written to exercise retrieval, which makes them
    exactly the corpus needed here: real questions, two videos, five kinds. If
    the heuristic ever starts matching one, an ordinary question is being sent
    down the summary path.
    """
    from app.services.question_kind import is_broad_question

    misrouted = [
        c["id"] for c in fixture_data["cases"]
        if c["kind"] != "off_topic" and is_broad_question(c["question"])
    ]
    assert not misrouted, (
        f"these retrieval cases would be routed to the summarisation path: {misrouted}"
    )
```

- [ ] **Step 6: Run the whole suite**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **247 passed, 1 skipped** (221 + 25 + 1). Report the actual number.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/question_kind.py backend/tests/test_question_kind.py backend/tests/test_retrieval_eval_fixture.py
git commit -m "feat: recognise broad questions without a model call"
```

---

### Task 2: Reading every chunk of a video

**Files:**
- Modify: `backend/app/services/vector_store/base.py`
- Modify: `backend/app/services/vector_store/memory.py`
- Modify: `backend/app/services/vector_store/postgres.py`
- Modify: `backend/app/services/vectorstore_service.py`
- Test: `backend/tests/test_vector_store_contract.py`

**Interfaces:**
- Produces: `VectorStore.list_video_chunks(video_id: str) -> list[TranscriptChunk]`, ordered by `index` ascending, empty list for an unknown video. Also `VectorStoreService.list_video_chunks(video_id)` delegating to the store.

- [ ] **Step 1: Write the failing contract tests**

Append to `backend/tests/test_vector_store_contract.py`. `make_chunk` and the
`store` fixture already exist in that file — use them.

```python
async def test_list_video_chunks_returns_every_chunk_in_index_order(store):
    # Inserted out of order so a backend that returns insertion order fails.
    await store.replace_video_chunks(
        "vid1",
        [make_chunk("vid1", i, [1.0, float(i) / 10, 0.0]) for i in (2, 0, 1)],
    )

    chunks = await store.list_video_chunks("vid1")

    assert [c.index for c in chunks] == [0, 1, 2]
    assert [c.chunk_id for c in chunks] == ["vid1-0", "vid1-1", "vid1-2"]


async def test_list_video_chunks_isolates_videos(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid2", [make_chunk("vid2", 0, [0.0, 1.0, 0.0])])

    assert [c.video_id for c in await store.list_video_chunks("vid1")] == ["vid1"]
    assert [c.video_id for c in await store.list_video_chunks("vid2")] == ["vid2"]


async def test_list_video_chunks_returns_empty_for_unknown_video(store):
    # Empty, not an error: an un-ingested video is an ordinary state, and the
    # summarisation path relies on being able to fall through quietly.
    assert await store.list_video_chunks("never-ingested") == []


async def test_list_video_chunks_preserves_timestamps_and_text(store):
    await store.replace_video_chunks(
        "vid1", [make_chunk("vid1", 3, [1.0, 0.0, 0.0], text="the important sentence")]
    )

    chunk = (await store.list_video_chunks("vid1"))[0]

    assert chunk.text == "the important sentence"
    assert chunk.start_seconds == 30.0
    assert chunk.end_seconds == 40.0
    assert chunk.segment_indices == [3]
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_contract.py -q -k list_video_chunks
```
Expected: FAIL — `AttributeError: 'InMemoryVectorStore' object has no attribute 'list_video_chunks'`.

- [ ] **Step 3: Add the method to the protocol**

In `backend/app/services/vector_store/base.py`, inside `class VectorStore(Protocol)`,
after `similarity_search`:

```python
    async def list_video_chunks(self, video_id: str) -> list[TranscriptChunk]:
        """Every stored chunk of one video, ordered by index ascending.

        Returns an empty list for a video that was never ingested - an ordinary
        state, not an error, since the summarisation path falls through quietly
        when it gets nothing.

        Unlike similarity_search this carries no embeddings in the result: the
        caller wants text and timestamps, and shipping 1536 floats per chunk
        across the wire for a whole video would be pure waste.
        """
        ...
```

- [ ] **Step 4: Implement in the in-memory store**

In `backend/app/services/vector_store/memory.py`, after `similarity_search`:

```python
    async def list_video_chunks(self, video_id: str) -> list[TranscriptChunk]:
        return sorted(self._by_video.get(video_id, []), key=lambda chunk: chunk.index)
```

- [ ] **Step 5: Implement in the pgvector store**

In `backend/app/services/vector_store/postgres.py`, after `similarity_search`:

```python
    async def list_video_chunks(self, video_id: str) -> list[TranscriptChunk]:
        # `embedding` is deliberately not selected: the caller wants text and
        # timestamps, and a whole video's worth of 1536-float vectors would be
        # transferred and parsed for nothing.
        statement = text(
            "select chunk_id, video_id, chunk_index, text, start_seconds, "
            "       end_seconds, segment_indices, token_estimate, source, language "
            "from transcript_chunks "
            "where video_id = :video_id "
            "order by chunk_index asc"
        )

        async with self._session_factory() as session:
            rows = (
                await session.execute(statement, {"video_id": video_id})
            ).mappings().all()

        return [
            TranscriptChunk(
                chunk_id=row["chunk_id"],
                index=row["chunk_index"],
                video_id=row["video_id"],
                text=row["text"],
                start_seconds=row["start_seconds"],
                end_seconds=row["end_seconds"],
                segment_indices=list(row["segment_indices"] or []),
                token_estimate=row["token_estimate"] or 0,
                metadata={
                    key: value
                    for key, value in (
                        ("source", row["source"]),
                        ("language", row["language"]),
                    )
                    if value is not None
                },
                embedding=None,
            )
            for row in rows
        ]
```

- [ ] **Step 6: Pass it through the service**

In `backend/app/services/vectorstore_service.py`, add to `VectorStoreService`
after `similarity_search`:

```python
    async def list_video_chunks(self, video_id: str) -> list[TranscriptChunk]:
        """Every chunk of one video, for callers that need the whole transcript.

        No embedding step, so unlike similarity_search this needs no credentials.
        """
        return await self.store.list_video_chunks(video_id)
```

- [ ] **Step 7: Run the contract suite**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_contract.py -q
```
Expected: PASS. Without `TEST_DATABASE_URL` only the memory backend runs; the
pgvector parameterisation is skipped, which is the existing convention.

Then the whole suite:

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **251 passed, 1 skipped** (247 + 4). Report the actual number.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/vector_store backend/app/services/vectorstore_service.py backend/tests/test_vector_store_contract.py
git commit -m "feat: let a vector store return every chunk of one video"
```

---

### Task 3: Transcript rebuilding and timestamp validation

**Files:**
- Create: `backend/app/services/summary.py`
- Test: `backend/tests/test_summary.py`

**Interfaces:**
- Produces:
  - `SUMMARY_PROMPT: ChatPromptTemplate` with variables `{transcript}` and `{question}`
  - `rebuild_transcript(chunks: list[TranscriptChunk]) -> str`
  - `extract_timestamps(text: str) -> list[float]`
  - `citations_for_timestamps(timestamps: list[float], chunks: list[TranscriptChunk]) -> list[TimestampCitation]`
- Consumes: `format_timestamp` from `app.services.rag_service`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_summary.py`:

```python
"""Pure helpers for the summarisation path.

All synchronous, no service construction, no key: transcript rebuilding and
timestamp validation are the parts most worth testing and the parts least
entangled with I/O.
"""

from app.schemas.chunks import TranscriptChunk
from app.services.summary import (
    citations_for_timestamps,
    extract_timestamps,
    rebuild_transcript,
)


def make_chunk(index: int, text: str, start: float, end: float, segments: list[int]) -> TranscriptChunk:
    return TranscriptChunk(
        chunk_id=f"vid-{index}",
        index=index,
        video_id="vid",
        text=text,
        start_seconds=start,
        end_seconds=end,
        segment_indices=segments,
        token_estimate=5,
        metadata={"source": "captions", "language": "en"},
    )


def test_rebuild_transcript_prefixes_each_chunk_with_its_timestamp() -> None:
    chunks = [
        make_chunk(0, "first part", 0.0, 65.0, [0, 1]),
        make_chunk(1, "second part", 65.0, 130.0, [1, 2]),
    ]

    rebuilt = rebuild_transcript(chunks)

    assert rebuilt == "[00:00] first part\n[01:05] second part"


def test_rebuild_transcript_orders_by_index_not_insertion() -> None:
    chunks = [
        make_chunk(2, "third", 20.0, 30.0, [2]),
        make_chunk(0, "first", 0.0, 10.0, [0]),
        make_chunk(1, "second", 10.0, 20.0, [1]),
    ]

    assert rebuild_transcript(chunks) == "[00:00] first\n[00:10] second\n[00:20] third"


def test_rebuild_transcript_drops_a_fully_duplicated_chunk() -> None:
    # A chunk whose segments are ALL already covered contributes nothing. The
    # one-segment boundary overlap is NOT removed - see the module docstring.
    chunks = [
        make_chunk(0, "the content", 0.0, 10.0, [0, 1]),
        make_chunk(1, "the content again", 0.0, 10.0, [0, 1]),
    ]

    assert rebuild_transcript(chunks) == "[00:00] the content"


def test_rebuild_transcript_of_nothing_is_empty() -> None:
    assert rebuild_transcript([]) == ""


def test_extract_timestamps_reads_both_formats() -> None:
    text = "The intro is at 00:00, loops at 05:18, and a long one at 01:02:03."

    assert extract_timestamps(text) == [0.0, 318.0, 3723.0]


def test_extract_timestamps_ignores_plain_numbers() -> None:
    assert extract_timestamps("There are 5 topics and 30 examples.") == []


def test_citations_keep_only_timestamps_inside_the_video() -> None:
    chunks = [
        make_chunk(0, "first", 0.0, 60.0, [0]),
        make_chunk(1, "second", 60.0, 120.0, [1]),
    ]

    # 30s is in chunk 0, 90s in chunk 1, 9999s is invented.
    citations = citations_for_timestamps([30.0, 90.0, 9999.0], chunks)

    assert [c.chunk_id for c in citations] == ["vid-0", "vid-1"]
    assert citations[0].timestamp == "00:00-01:00"


def test_citations_deduplicate_repeated_chunks() -> None:
    chunks = [make_chunk(0, "first", 0.0, 60.0, [0])]

    # Two marks landing in the same chunk must not produce two citations.
    assert len(citations_for_timestamps([10.0, 20.0], chunks)) == 1


def test_citations_of_nothing_is_empty() -> None:
    assert citations_for_timestamps([12.0], []) == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_summary.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.summary'`.

- [ ] **Step 3: Implement**

Create `backend/app/services/summary.py`:

```python
"""Building a whole-video summary and validating the timestamps it claims.

Everything here is pure. The service that calls it owns the model call and the
error handling; this module owns the text.

On deduplication: TranscriptChunk stores its text as one concatenated string
plus a list of segment indices - NOT per-segment text. So when chunk N covers
segments 10-20 and chunk N+1 covers 20-30, segment 20's words are inside both
strings and cannot be removed without the original segments. rebuild_transcript
therefore drops only chunks whose segments are ENTIRELY already seen, and the
one-segment boundary overlap remains: a few repeated words per boundary, about
2% of the text, immaterial to a summary. The design spec claims full dedup; it
is wrong, and this is the correction.
"""

import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from app.schemas.chunks import TranscriptChunk
from app.schemas.rag import TimestampCitation
from app.services.rag_service import format_timestamp

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are AskTube AI. You are given a full video transcript in which "
                "every section is prefixed with its timestamp in [MM:SS] form. "
                "Summarise what the video covers, as a short overview followed by the "
                "main points in the order they appear. "
                "Start every main point with the timestamp of the section it comes "
                "from, copied EXACTLY from the transcript - never invent or estimate a "
                "timestamp, and never use one that does not appear above. "
                "Use only what the transcript contains. Do not add outside knowledge."
            ),
        ),
        ("human", "Transcript:\n{transcript}\n\nUser question:\n{question}"),
    ]
)

# Matches 05:18 and 01:02:03. The leading \b stops it from cutting into a longer
# digit run, so "10530:12" is not read as a timestamp.
_TIMESTAMP_RE = re.compile(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b")


def rebuild_transcript(chunks: list[TranscriptChunk]) -> str:
    """One timestamped line per chunk, ordered by index."""
    lines: list[str] = []
    seen_segments: set[int] = set()

    for chunk in sorted(chunks, key=lambda item: item.index):
        if chunk.segment_indices and all(i in seen_segments for i in chunk.segment_indices):
            continue

        seen_segments.update(chunk.segment_indices)
        lines.append(f"[{format_timestamp(chunk.start_seconds)}] {chunk.text}")

    return "\n".join(lines)


def extract_timestamps(text: str) -> list[float]:
    """Every timestamp mentioned in the model's answer, as seconds."""
    seconds: list[float] = []

    for hours, minutes, secs in _TIMESTAMP_RE.findall(text):
        total = int(minutes) * 60 + int(secs)
        if hours:
            total += int(hours) * 3600
        seconds.append(float(total))

    return seconds


def citations_for_timestamps(
    timestamps: list[float],
    chunks: list[TranscriptChunk],
) -> list[TimestampCitation]:
    """Turn claimed timestamps into citations, dropping the ones that are not real.

    A model can emit a timestamp that exists nowhere in the video. Attaching a
    citation object to it would assert a source that does not exist, which is
    worse than having no citation at all - so an unmatched mark is logged and
    discarded.
    """
    if not chunks:
        return []

    ordered = sorted(chunks, key=lambda item: item.start_seconds)
    citations: list[TimestampCitation] = []
    seen_chunks: set[str] = set()

    for timestamp in timestamps:
        match = next(
            (c for c in ordered if c.start_seconds <= timestamp <= c.end_seconds), None
        )
        if match is None:
            logger.warning(
                "Summary claimed timestamp %s, which matches no chunk of the video; "
                "dropping the citation.",
                format_timestamp(timestamp),
            )
            continue

        if match.chunk_id in seen_chunks:
            continue

        seen_chunks.add(match.chunk_id)
        citations.append(
            TimestampCitation(
                chunk_id=match.chunk_id,
                video_id=match.video_id,
                start_seconds=match.start_seconds,
                end_seconds=match.end_seconds,
                timestamp=(
                    f"{format_timestamp(match.start_seconds)}-"
                    f"{format_timestamp(match.end_seconds)}"
                ),
                text=match.text,
            )
        )

    return citations
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_summary.py -q
```
Expected: PASS — 9 tests.

- [ ] **Step 5: Run the whole suite**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **260 passed, 1 skipped** (251 + 9). Report the actual number.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/summary.py backend/tests/test_summary.py
git commit -m "feat: rebuild a timestamped transcript and validate claimed timestamps"
```

---

### Task 4: Wire the summarisation path into `answer()`

**Files:**
- Modify: `backend/app/services/rag_service.py`
- Test: `backend/tests/test_rag_service.py`

**Interfaces:**
- Consumes: `is_broad_question` (Task 1), `list_video_chunks` (Task 2), `rebuild_transcript` / `extract_timestamps` / `citations_for_timestamps` / `SUMMARY_PROMPT` (Task 3).
- Produces: `RAGService.summarize_video(message: str, video_id: str) -> tuple[str, list[TimestampCitation]] | None`. No `session_id`: the method produces text and citations, and the caller owns the session. Returns `None` when the path cannot or should not run, which is the caller's signal to fall through.

**Import note:** `summary.py` imports `format_timestamp` from `rag_service.py`, so
`rag_service.py` must import from `summary` **inside** `summarize_video`, not at
module top level, or the two modules form an import cycle.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_rag_service.py`. `make_rag_service`,
`CapturingVectorStoreService` and `FakeListChatModel` already exist there.

```python
# ---------------------------------------------------------------------------
# Broad questions take the summarisation path
# ---------------------------------------------------------------------------


class ChunkListingVectorStoreService(CapturingVectorStoreService):
    """A store that can also hand back a whole video."""

    def __init__(self, chunks) -> None:  # noqa: ANN001
        super().__init__()
        self._chunks = chunks

    async def list_video_chunks(self, video_id):  # noqa: ANN001
        return list(self._chunks)


def make_video_chunks() -> list:
    from app.schemas.chunks import TranscriptChunk

    return [
        TranscriptChunk(
            chunk_id=f"vid1-{i}", index=i, video_id="vid1",
            text=f"section {i} of the video", start_seconds=float(i * 60),
            end_seconds=float(i * 60 + 60), segment_indices=[i], token_estimate=5,
            metadata={"source": "captions", "language": "en"},
        )
        for i in range(3)
    ]


async def test_broad_question_is_answered_from_the_whole_transcript(monkeypatch) -> None:  # noqa: ANN001
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(
            responses=["Overview. [00:00] the start. [02:30] the end."]
        ),
    )

    response = await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    # The search was never used: a summary is not a retrieval answer.
    assert service.vectorstore.last_query is None
    assert "Overview" in response.answer
    # 00:00 lands in chunk 0 (0-60s), 02:30 in chunk 2 (120-180s). Deliberately
    # NOT 02:00, which is the boundary between chunks 1 and 2 and would encode
    # an arbitrary tie-break into the test.
    assert [c.chunk_id for c in response.citations] == ["vid1-0", "vid1-2"]
    assert response.retrieved_context == []


async def test_narrow_question_still_takes_the_retrieval_path(monkeypatch) -> None:  # noqa: ANN001
    # The constraint that matters most: nothing else changes.
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    await service.answer(
        message="How do I do addition in Python?", video_id="vid1", session_id=None, top_k=5
    )

    assert service.vectorstore.last_query == "How do I do addition in Python?"


async def test_summary_falls_back_to_retrieval_when_the_model_fails(monkeypatch) -> None:  # noqa: ANN001
    # Degrade, do not fail: a broken summary must still produce the answer the
    # user would have got before this feature existed.
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FailingChatModel(responses=["unused"]),
    )

    response = await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    # The retrieval path ran instead - proven by the search having happened.
    assert service.vectorstore.last_query == "What is this video about?"
    assert response.answer


async def test_summary_falls_back_when_the_video_has_no_chunks(monkeypatch) -> None:  # noqa: ANN001
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService([])
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    response = await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    assert service.vectorstore.last_query == "What is this video about?"
    assert response.answer


async def test_summary_falls_back_when_the_transcript_is_too_long(monkeypatch) -> None:  # noqa: ANN001
    from app.schemas.chunks import TranscriptChunk

    huge = [
        TranscriptChunk(
            chunk_id="vid1-0", index=0, video_id="vid1", text="x" * 41_000,
            start_seconds=0.0, end_seconds=60.0, segment_indices=[0],
            token_estimate=5, metadata={"source": "captions", "language": "en"},
        )
    ]
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(huge)
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    await service.answer(
        message="What is this video about?", video_id="vid1", session_id=None, top_k=5
    )

    assert service.vectorstore.last_query == "What is this video about?"


async def test_broad_question_without_a_video_takes_the_retrieval_path(monkeypatch) -> None:  # noqa: ANN001
    # There is nothing to summarise when no video is named.
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["a grounded answer"]),
    )

    await service.answer(
        message="What is this video about?", video_id=None, session_id=None, top_k=5
    )

    assert service.vectorstore.last_query == "What is this video about?"
```

`CapturingVectorStoreService.__init__` sets `self.last_query = None`, so the
`is None` assertion in the first test is meaningful.

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_rag_service.py -q -k "broad or summary or narrow_question"
```
Expected: FAIL — the first test fails on `last_query` being the raw message,
because no branch exists yet.

- [ ] **Step 3: Add `SUMMARY_MAX_CHARS` and `summarize_video`**

In `backend/app/services/rag_service.py`, add near the top after `logger`:

```python
# Above this the transcript will not fit alongside the prompt and the answer.
# A judgement, not a measurement: far above both evaluation videos (10k and 14k)
# and far below the model's context limit.
SUMMARY_MAX_CHARS = 40_000
```

Then add this method to `RAGService`, directly after `_contextualize`:

```python
    async def summarize_video(
        self,
        message: str,
        video_id: str,
    ) -> tuple[str, list[TimestampCitation]] | None:
        """Summarise a whole video, or return None to fall through to retrieval.

        None is not an error signal - it means "this path cannot help here", and
        every such case is one the retrieval path already handles. The
        summarisation path is an enhancement, so it degrades rather than failing,
        the same way conversation memory and the query rewrite do.
        """
        # Imported here, not at module scope: summary.py imports format_timestamp
        # from this module, so a top-level import would be circular.
        from app.services.summary import (
            SUMMARY_PROMPT,
            citations_for_timestamps,
            extract_timestamps,
            rebuild_transcript,
        )

        try:
            chunks = await self.vectorstore.list_video_chunks(video_id)
        except Exception as exc:  # noqa: BLE001 - see _contextualize for the rationale
            logger.warning("Could not read chunks for %s: %s", video_id, exc)
            return None

        if not chunks:
            logger.info("No chunks stored for %s; not summarising.", video_id)
            return None

        transcript = rebuild_transcript(chunks)
        if len(transcript) > SUMMARY_MAX_CHARS:
            logger.warning(
                "Transcript for %s is %d characters, over the %d limit; "
                "answering by retrieval instead.",
                video_id, len(transcript), SUMMARY_MAX_CHARS,
            )
            return None

        try:
            chain = SUMMARY_PROMPT | self.create_chat_model(streaming=False)
            response = await chain.ainvoke(
                {"transcript": transcript, "question": message},
                config={"run_name": "video_summary", "tags": ["rag", "summary"]},
            )
            answer = str(response.content).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Summarisation failed for %s: %s", video_id, exc)
            return None

        if not answer:
            logger.warning("Summarisation returned empty text for %s.", video_id)
            return None

        return answer, citations_for_timestamps(extract_timestamps(answer), chunks)
```

- [ ] **Step 4: Branch in `answer()`**

In `answer()`, immediately after `answer_start = time.perf_counter()` and before
`retrieval_start = time.perf_counter()`, insert:

```python
        if is_broad_question(message) and video_id is not None:
            summary = await self.summarize_video(message=message, video_id=video_id)
            if summary is not None:
                summary_answer, summary_citations = summary
                active_session_id = session_id or self.memory.create_session_id()
                await self._append_exchange(active_session_id, message, summary_answer)
                messages = await self._get_history(active_session_id)
                await self._record_rag_metrics(
                    message=message,
                    session_id=active_session_id,
                    retrieved_context=[],
                    citations=summary_citations,
                    answer=summary_answer,
                    retrieval_ms=0,
                    generation_ms=(time.perf_counter() - answer_start) * 1000,
                    started_at=answer_start,
                    messages=messages,
                )
                return RAGChatResponse(
                    session_id=active_session_id,
                    answer=summary_answer,
                    citations=summary_citations,
                    # Empty on purpose: no chunk selection took place, and listing
                    # the chunks that fed the summary would misrepresent that.
                    retrieved_context=[],
                    memory=messages,
                )
```

Add the import at the top of `rag_service.py`, with the other `app.services` imports:

```python
from app.services.question_kind import is_broad_question
```

- [ ] **Step 5: Run the new tests**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_rag_service.py -q
```
Expected: PASS, including the six new tests.

- [ ] **Step 6: Run the whole suite**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **266 passed, 1 skipped** (260 + 6). Report the actual number.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/rag_service.py backend/tests/test_rag_service.py
git commit -m "feat: answer broad questions from the whole transcript"
```

---

### Task 5: The same branch in the streaming path

**Files:**
- Modify: `backend/app/services/rag_service.py`
- Test: `backend/tests/test_rag_service.py`

**Interfaces:**
- Consumes: `RAGService.summarize_video` from Task 4.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_rag_service.py`:

```python
async def test_stream_answer_emits_a_summary_as_one_token_event(monkeypatch) -> None:  # noqa: ANN001
    # The model call is not streamed, so pretending to stream it would only add
    # machinery. One token event, then done.
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FakeListChatModel(responses=["Overview. [00:00] the start."]),
    )

    events = [
        event
        async for event in service.stream_answer(
            message="What is this video about?", video_id="vid1", session_id=None, top_k=5
        )
    ]

    types = [e.type for e in events]
    assert types == ["context", "token", "done"]
    assert events[1].token == "Overview. [00:00] the start."
    assert events[-1].answer == "Overview. [00:00] the start."
    assert [c.chunk_id for c in events[-1].citations] == ["vid1-0"]
    assert events[0].retrieved_context == []


async def test_stream_answer_falls_back_to_retrieval_when_summarising_fails(monkeypatch) -> None:  # noqa: ANN001
    service = make_rag_service()
    service.vectorstore = ChunkListingVectorStoreService(make_video_chunks())
    monkeypatch.setattr(
        service, "create_chat_model",
        lambda streaming: FailingChatModel(responses=["unused"]),
    )

    events = [
        event
        async for event in service.stream_answer(
            message="What is this video about?", video_id="vid1", session_id=None, top_k=5
        )
    ]

    assert service.vectorstore.last_query == "What is this video about?"
    assert events[-1].type == "done"
```

The second test's generation will also fail (the same failing model), so the
`done` event carries whatever the retrieval path produces on a failed
generation. The assertion is deliberately only that the stream completed and
that the retrieval search ran — that is what "fell back" means here.

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_rag_service.py -q -k stream_answer_emits
```
Expected: FAIL — `types` will be `["context", "token", "done"]` from the ordinary
path but the citations will not match, because no summary branch exists yet.

- [ ] **Step 3: Implement**

In `stream_answer()`, immediately after `answer_start = time.perf_counter()`,
insert:

```python
        if is_broad_question(message) and video_id is not None:
            summary = await self.summarize_video(message=message, video_id=video_id)
            if summary is not None:
                summary_answer, summary_citations = summary
                active_session_id = session_id or self.memory.create_session_id()
                history = await self._get_history(active_session_id)
                yield RAGStreamEvent(
                    type="context",
                    session_id=active_session_id,
                    citations=summary_citations,
                    retrieved_context=[],
                    memory=history,
                )
                yield RAGStreamEvent(
                    type="token", session_id=active_session_id, token=summary_answer
                )
                await self._append_exchange(active_session_id, message, summary_answer)
                messages = await self._get_history(active_session_id)
                await self._record_rag_metrics(
                    message=message,
                    session_id=active_session_id,
                    retrieved_context=[],
                    citations=summary_citations,
                    answer=summary_answer,
                    retrieval_ms=0,
                    generation_ms=(time.perf_counter() - answer_start) * 1000,
                    started_at=answer_start,
                    messages=messages,
                )
                yield RAGStreamEvent(
                    type="done",
                    session_id=active_session_id,
                    answer=summary_answer,
                    citations=summary_citations,
                    retrieved_context=[],
                    memory=messages,
                )
                return
```

- [ ] **Step 4: Run the whole suite**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **268 passed, 1 skipped** (266 + 2). Report the actual number.

- [ ] **Step 5: Verify the frontend is untouched**

```bash
cd frontend && npx tsc --noEmit && npm test
```
Expected: **79 passed**.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/rag_service.py backend/tests/test_rag_service.py
git commit -m "feat: emit a summary through the streaming path too"
```

---

### Task 6: Documentation

**Files:**
- Modify: `AGENTS.md`, and regenerate `CLAUDE.md` from it

- [ ] **Step 1: Document the behaviour**

Add to the Configuration section of `AGENTS.md`, after the chunk-size bullet:

```markdown
- Summarisation path: a **broad** question ("what is this video about?") does not
  go through retrieval. `is_broad_question` in
  `backend/app/services/question_kind.py` classifies it with a **pure pattern
  match — no model call**, deliberately: an LLM classifier would be
  non-deterministic, would add latency to every request, and would break the
  documented guarantee that a first turn makes no model call (broad questions
  are usually first turns). The cost is that only phrasings someone listed are
  recognised; a miss falls through to retrieval, which is the old behaviour, so
  it is never a regression.
  `RAGService.summarize_video` then reads EVERY chunk via the vector store's
  `list_video_chunks`, rebuilds a timestamped transcript and makes **one** chat
  call. Timestamps in the answer are validated against real chunks before
  becoming citations — an invented mark is logged and dropped rather than
  asserted as a source.
  **It degrades, it does not fail**: no chunks, a transcript over
  `SUMMARY_MAX_CHARS` (40,000), a failed or empty model call — each returns
  `None` and the question is answered by retrieval instead.
  `retrieved_context` comes back **empty** on this path, because no chunk
  selection happened. Do not "fix" that by listing the chunks that fed the
  summary.
  The regression guard is free and already written:
  `test_no_content_case_is_classified_as_broad` asserts that none of the 26
  content cases in the retrieval fixture classify as broad.
  Known limits: timestamp **validity** is not timestamp **correctness** — a mark
  can be inside the video and match a chunk while still pointing at the wrong
  moment. And whether a summary is *good* is not measured at all; there is no
  ground truth for it, and inventing a number would produce something that looks
  like evidence and is not.
```

- [ ] **Step 2: Update the test counts**

Replace the two counts in the Testing section with the numbers actually reported
by the final suite run in Task 5, keeping the existing "derived, not separately
measured" wording for the without-extras figure.

- [ ] **Step 3: Regenerate `CLAUDE.md`**

```bash
cd "C:/Users/sisaz/PycharmProjects/asktube-ai" && python -c "
from pathlib import Path
a = Path('AGENTS.md').read_text(encoding='utf-8')
Path('CLAUDE.md').write_text(a.replace('# AskTube AI — project context for Codex','# AskTube AI — project context for Claude Code',1), encoding='utf-8')
print('CLAUDE.md regenerated')
"
```

- [ ] **Step 4: Verify and commit**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```

```bash
git add AGENTS.md
git commit -m "docs: record the summarisation path and what it does not measure"
```

---

### Task 7: Live verification (operator)

An agent cannot run this — it needs the deployed database and a real key.

- [ ] **Step 1: Ask a broad question against an ingested video**

```bash
cd backend && python -c "
import asyncio
from app.services.rag_service import get_rag_service
r = asyncio.run(get_rag_service().answer(message='What is this video about?', video_id='fWjsdhR3z3c', session_id=None, top_k=5))
print(r.answer)
print()
for c in r.citations:
    print(' ', c.timestamp, '|', c.text[:60])
"
```

- [ ] **Step 2: Check the three things that matter**

- The answer describes the **whole** video, not one passage.
- **Every** citation timestamp falls inside the video's real duration. A mark
  beyond the end means validation is not working — that is a bug, not a quirk.
- `retrieved_context` is empty.

- [ ] **Step 3: Confirm nothing else moved**

```bash
cd backend && python scripts/run_retrieval_eval.py --frozen
```
Expected: **28/29**, unchanged from before this feature. A different number means
the branch is catching questions it should not.

---

## What this plan deliberately does not do

- **No map-reduce.** Videos over 40,000 characters fall through to retrieval
  rather than being summarised in pieces. That is a real limitation, chosen
  knowingly, and the guard makes it visible in the log rather than as a crash.
- **No LLM classifier.** See Task 1's docstring for why.
- **No judgement of summary quality.** It would need an LLM judge, which is its
  own feature with its own failure modes.
- **No agent-path support.** `agent_service` has its own tool loop and would need
  its own decision.
- **No frontend change.** Citations already render as clickable timestamps.
