# Phase 2a: Vector Store Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `VectorStore` protocol with an in-memory and a pgvector implementation, proven identical by a shared contract suite — without changing any existing behaviour.

**Architecture:** A new `app/services/vector_store/` package owns persistence only. Nothing consumes it in this plan: every existing call site still uses `ChromaVectorStoreService`. The cutover is Phase 2b, and it happens against a component already proven working.

**Tech Stack:** SQLAlchemy 2.0 async, asyncpg, pgvector, Alembic, pytest / pytest-asyncio in `auto` mode.

## Global Constraints

- Deployment stays at **$0/month**.
- **No behaviour change.** Nothing in this plan is wired into a route, service or tool. Every existing test must pass untouched.
- **No new runtime dependencies except `pgvector`.** Specifically **do not add numpy** — it is absent from `requirements.txt` and arrives only transitively via `chromadb`, which Phase 2b deletes. Cosine similarity is computed in pure Python.
- Baseline before this plan: **157 passed, 1 skipped** (with local-embedding extras; the skip is the Alembic migration test). New pgvector tests skip without `TEST_DATABASE_URL` and must never fail on a machine without a database.
- Frontend untouched: `npx tsc --noEmit && npm test` → **79 passed**.
- Distance is **cosine**: pgvector `<=>`, matching Chroma's `hnsw:space: cosine`. Both compute `1 − cosine_similarity`, so `VectorSearchResult.distance` keeps its existing meaning and scale.
- Embedding dimension is **1536** (`text-embedding-3-small`), configurable at migration time.
- Migration `0002` must set `down_revision = "0001"`.
- Never commit credentials.
- Work on branch `phase2/pgvector-retrieval`. Do not push to `main`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/alembic/script.py.mako` | Alembic revision template (missing since Phase 1) |
| `backend/app/services/vector_store/__init__.py` | Package exports |
| `backend/app/services/vector_store/base.py` | `VectorStore` protocol, `cosine_distance`, `chunk_to_result` |
| `backend/app/services/vector_store/memory.py` | In-memory implementation for dev/CI |
| `backend/app/services/vector_store/postgres.py` | pgvector implementation |
| `backend/alembic/versions/0002_transcript_chunks.py` | `transcript_chunks` table + HNSW index |
| `backend/tests/test_vector_store_contract.py` | Shared contract suite over both implementations |

---

### Task 1: Alembic revision template

Phase 1 shipped without `script.py.mako`, so `alembic revision` fails with `TemplateNotFound`. Task 5 needs it.

**Files:**
- Create: `backend/alembic/script.py.mako`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `alembic revision` command. No Python API.

- [ ] **Step 1: Create the template**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 2: Verify the command now works**

Run:
```bash
cd backend && python -m alembic revision -m "template smoke test"
```
Expected: prints `Generating ... _template_smoke_test.py ... done`, exit 0.

- [ ] **Step 3: Delete the throwaway revision**

The generated file was only to prove the template parses. Delete it:
```bash
cd backend && git status --short alembic/versions/
```
Remove the newly generated `alembic/versions/*_template_smoke_test.py` file. Confirm `alembic/versions/` contains only `0001_initial_analytics.py`.

- [ ] **Step 4: Confirm the suite is unaffected**

Run:
```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **157 passed, 1 skipped**.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/script.py.mako
git commit -m "fix: add missing alembic revision template"
```

---

### Task 2: Protocol and shared helpers

**Files:**
- Create: `backend/app/services/vector_store/__init__.py`, `backend/app/services/vector_store/base.py`
- Test: `backend/tests/test_vector_store_base.py`

**Interfaces:**
- Consumes: `TranscriptChunk` from `app.schemas.chunks`, `VectorSearchResult` from `app.schemas.vectorstore`.
- Produces:
  - `VectorStore` — a `typing.Protocol` with `async replace_video_chunks(video_id: str, chunks: list[TranscriptChunk]) -> list[str]` and `async similarity_search(query_embedding: list[float], limit: int = 5, video_id: str | None = None) -> list[VectorSearchResult]`
  - `cosine_distance(a: list[float], b: list[float]) -> float`
  - `chunk_to_result(chunk: TranscriptChunk, distance: float | None) -> VectorSearchResult`

  Tasks 3, 5 and 6 all depend on these exact names and signatures.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_vector_store_base.py`:

```python
import math

import pytest

from app.schemas.chunks import TranscriptChunk
from app.services.vector_store.base import chunk_to_result, cosine_distance


def make_chunk(**overrides) -> TranscriptChunk:
    data = {
        "chunk_id": "vid1-0",
        "index": 0,
        "video_id": "vid1",
        "text": "hello world",
        "start_seconds": 0.0,
        "end_seconds": 5.0,
        "segment_indices": [0, 1],
        "token_estimate": 3,
        "metadata": {"source": "captions", "language": "en"},
        "embedding": [1.0, 0.0],
    }
    data.update(overrides)
    return TranscriptChunk(**data)


def test_identical_vectors_have_zero_distance():
    assert cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


def test_orthogonal_vectors_have_distance_one():
    assert cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)


def test_opposite_vectors_have_distance_two():
    assert cosine_distance([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(2.0)


def test_magnitude_does_not_affect_distance():
    # Cosine compares direction only; a scaled vector must match exactly.
    assert cosine_distance([1.0, 2.0], [10.0, 20.0]) == pytest.approx(0.0)


def test_zero_vector_yields_max_distance_rather_than_dividing_by_zero():
    assert cosine_distance([0.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_dimension_mismatch_raises_clear_error():
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_distance([1.0, 0.0], [1.0, 0.0, 0.0])


def test_chunk_to_result_maps_fields_and_filters_metadata():
    chunk = make_chunk(metadata={"source": "captions", "bad": [1, 2]})
    result = chunk_to_result(chunk, 0.25)
    assert result.chunk_id == "vid1-0"
    assert result.video_id == "vid1"
    assert result.text == "hello world"
    assert result.start_seconds == 0.0
    assert result.end_seconds == 5.0
    assert result.segment_indices == [0, 1]
    assert result.distance == 0.25
    # VectorSearchResult.metadata only allows scalars; list values are dropped.
    assert result.metadata == {"source": "captions"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_base.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.vector_store'`.

- [ ] **Step 3: Create the package**

Create `backend/app/services/vector_store/__init__.py`:

```python
from app.services.vector_store.base import VectorStore, chunk_to_result, cosine_distance

__all__ = ["VectorStore", "chunk_to_result", "cosine_distance"]
```

Create `backend/app/services/vector_store/base.py`:

```python
import math
from typing import Protocol

from app.schemas.chunks import TranscriptChunk
from app.schemas.vectorstore import VectorSearchResult


class VectorStore(Protocol):
    """Persistence for transcript chunk embeddings.

    Implementations store and retrieve vectors and nothing else: embedding
    generation lives above them, so it exists once rather than being duplicated
    per backend.
    """

    async def replace_video_chunks(
        self,
        video_id: str,
        chunks: list[TranscriptChunk],
    ) -> list[str]:
        """Replace every stored chunk for video_id with chunks; return stored ids.

        Replace rather than upsert: chunk ids derive from chunking parameters, so
        upserting after a parameter change leaves the old chunks behind forever and
        retrieval silently mixes two chunkings of the same video.
        """
        ...

    async def similarity_search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        video_id: str | None = None,
    ) -> list[VectorSearchResult]:
        """Return the closest chunks by cosine distance, nearest first."""
        ...


def cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance in pure Python: 1 - cosine_similarity.

    Matches pgvector's `<=>` operator and Chroma's `hnsw:space: cosine`, so the
    value carries the same meaning across every backend.

    Deliberately not numpy — numpy is not a direct dependency and arrives only via
    chromadb, which is being removed.
    """
    if len(a) != len(b):
        raise ValueError(f"embedding dimension mismatch: {len(a)} != {len(b)}")

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0

    return 1.0 - (dot / (norm_a * norm_b))


def chunk_to_result(chunk: TranscriptChunk, distance: float | None) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk.chunk_id,
        video_id=chunk.video_id,
        text=chunk.text,
        start_seconds=chunk.start_seconds,
        end_seconds=chunk.end_seconds,
        segment_indices=chunk.segment_indices,
        distance=distance,
        metadata={
            key: value
            for key, value in chunk.metadata.items()
            if isinstance(value, str | int | float)
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_base.py -v
```
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/vector_store backend/tests/test_vector_store_base.py
git commit -m "feat: add VectorStore protocol and pure-python cosine distance"
```

---

### Task 3: In-memory implementation

**Files:**
- Create: `backend/app/services/vector_store/memory.py`
- Modify: `backend/app/services/vector_store/__init__.py`
- Test: covered by Task 4's contract suite. This task adds no test file of its own.

**Interfaces:**
- Consumes: `VectorStore`, `cosine_distance`, `chunk_to_result` from Task 2.
- Produces: `InMemoryVectorStore` with a no-argument constructor. Tasks 4 and 6 instantiate it as `InMemoryVectorStore()`.

- [ ] **Step 1: Implement**

Create `backend/app/services/vector_store/memory.py`:

```python
from app.schemas.chunks import TranscriptChunk
from app.schemas.vectorstore import VectorSearchResult
from app.services.vector_store.base import chunk_to_result, cosine_distance


class InMemoryVectorStore:
    """Process-local vector store for development and tests.

    Replaces the role ChromaDB filled accidentally: letting the suite run with no
    infrastructure. The contract suite is what keeps it honest against pgvector.
    """

    def __init__(self) -> None:
        self._by_video: dict[str, list[TranscriptChunk]] = {}

    async def replace_video_chunks(
        self,
        video_id: str,
        chunks: list[TranscriptChunk],
    ) -> list[str]:
        self._by_video[video_id] = list(chunks)
        return [chunk.chunk_id for chunk in chunks]

    async def similarity_search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        video_id: str | None = None,
    ) -> list[VectorSearchResult]:
        if video_id is not None:
            candidates = self._by_video.get(video_id, [])
        else:
            candidates = [chunk for chunks in self._by_video.values() for chunk in chunks]

        scored: list[tuple[float, TranscriptChunk]] = [
            (cosine_distance(query_embedding, chunk.embedding), chunk)
            for chunk in candidates
            if chunk.embedding is not None
        ]
        scored.sort(key=lambda pair: pair[0])

        return [chunk_to_result(chunk, distance) for distance, chunk in scored[:limit]]
```

Update `backend/app/services/vector_store/__init__.py`:

```python
from app.services.vector_store.base import VectorStore, chunk_to_result, cosine_distance
from app.services.vector_store.memory import InMemoryVectorStore

__all__ = ["InMemoryVectorStore", "VectorStore", "chunk_to_result", "cosine_distance"]
```

- [ ] **Step 2: Verify it imports and satisfies the protocol shape**

Run:
```bash
cd backend && python -c "
from app.services.vector_store import InMemoryVectorStore, VectorStore
store = InMemoryVectorStore()
assert hasattr(store, 'replace_video_chunks')
assert hasattr(store, 'similarity_search')
print('ok')
"
```
Expected: prints `ok`.

- [ ] **Step 3: Confirm nothing else broke**

Run:
```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **164 passed, 1 skipped** (157 baseline + Task 2's 7 tests).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/vector_store
git commit -m "feat: add in-memory vector store implementation"
```

---

### Task 4: Contract suite

The suite that makes deleting Chroma safe later: it asserts behaviour, not implementation, and every backend must satisfy it identically.

**Files:**
- Create: `backend/tests/test_vector_store_contract.py`

**Interfaces:**
- Consumes: `InMemoryVectorStore` (Task 3).
- Produces: a pytest fixture named `store`, parameterised over backends. Task 6 extends its params with pgvector; the test bodies must not need changing when that happens.

- [ ] **Step 1: Write the contract suite**

Create `backend/tests/test_vector_store_contract.py`:

```python
import pytest

from app.schemas.chunks import TranscriptChunk
from app.services.vector_store import InMemoryVectorStore


def make_chunk(video_id: str, index: int, embedding: list[float], text: str = "") -> TranscriptChunk:
    return TranscriptChunk(
        chunk_id=f"{video_id}-{index}",
        index=index,
        video_id=video_id,
        text=text or f"chunk {index} of {video_id}",
        start_seconds=float(index * 10),
        end_seconds=float(index * 10 + 10),
        segment_indices=[index],
        token_estimate=5,
        metadata={"source": "captions", "language": "en"},
        embedding=embedding,
    )


# Task 6 appends the pgvector backend here. Test bodies stay unchanged.
@pytest.fixture(params=["memory"])
def store(request):
    if request.param == "memory":
        return InMemoryVectorStore()
    raise AssertionError(f"unknown backend {request.param}")


async def test_stored_chunk_is_retrievable(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    results = await store.similarity_search([1.0, 0.0, 0.0], limit=5)
    assert [r.chunk_id for r in results] == ["vid1-0"]


async def test_results_are_ordered_nearest_first(store):
    await store.replace_video_chunks(
        "vid1",
        [
            make_chunk("vid1", 0, [0.0, 1.0, 0.0]),   # orthogonal to query
            make_chunk("vid1", 1, [1.0, 0.0, 0.0]),   # identical to query
        ],
    )
    results = await store.similarity_search([1.0, 0.0, 0.0], limit=5)
    assert [r.chunk_id for r in results] == ["vid1-1", "vid1-0"]
    assert results[0].distance < results[1].distance


async def test_limit_is_respected(store):
    # Insert chunks in REVERSED order (4, 3, 2, 1, 0) so that a backend returning
    # "the first two inserted" would fail. Only backends that sort before limiting
    # correctly return [vid1-0, vid1-1] (the two nearest by cosine distance).
    await store.replace_video_chunks(
        "vid1",
        [make_chunk("vid1", i, [1.0, float(i) / 10, 0.0]) for i in reversed(range(5))],
    )
    results = await store.similarity_search([1.0, 0.0, 0.0], limit=2)
    assert len(results) == 2
    assert [r.chunk_id for r in results] == ["vid1-0", "vid1-1"]


Asserting both length and exact identity (not just count) is what discriminates "limit before sort" errors — inserting in reversed order ensures a broken backend that truncated before scoring would return different chunk ids.


async def test_video_id_filter_isolates_videos(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid2", [make_chunk("vid2", 0, [1.0, 0.0, 0.0])])

    results = await store.similarity_search([1.0, 0.0, 0.0], limit=10, video_id="vid1")
    assert [r.video_id for r in results] == ["vid1"]

    unfiltered = await store.similarity_search([1.0, 0.0, 0.0], limit=10)
    assert {r.video_id for r in unfiltered} == {"vid1", "vid2"}


async def test_reingest_replaces_rather_than_accumulates(store):
    """The stale-chunk bug: re-chunking changes ids, and upsert would keep both sets."""
    await store.replace_video_chunks(
        "vid1",
        [make_chunk("vid1", 0, [1.0, 0.0, 0.0]), make_chunk("vid1", 1, [0.0, 1.0, 0.0])],
    )
    # Re-ingest with different chunking: one chunk, a different id.
    replacement = make_chunk("vid1", 99, [1.0, 0.0, 0.0])
    await store.replace_video_chunks("vid1", [replacement])

    results = await store.similarity_search([1.0, 0.0, 0.0], limit=10, video_id="vid1")
    assert [r.chunk_id for r in results] == ["vid1-99"]


async def test_replacing_one_video_leaves_others_untouched(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid2", [make_chunk("vid2", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 7, [1.0, 0.0, 0.0])])

    remaining = await store.similarity_search([1.0, 0.0, 0.0], limit=10, video_id="vid2")
    assert [r.chunk_id for r in remaining] == ["vid2-0"]


async def test_search_on_empty_store_returns_empty_list(store):
    assert await store.similarity_search([1.0, 0.0, 0.0], limit=5) == []


async def test_replace_with_empty_list_clears_the_video(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0, 0.0])])
    await store.replace_video_chunks("vid1", [])
    assert await store.similarity_search([1.0, 0.0, 0.0], limit=5, video_id="vid1") == []


async def test_result_carries_timestamps_and_metadata(store):
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 3, [1.0, 0.0, 0.0])])
    result = (await store.similarity_search([1.0, 0.0, 0.0], limit=1))[0]
    assert result.start_seconds == 30.0
    assert result.end_seconds == 40.0
    assert result.segment_indices == [3]
    assert result.metadata["source"] == "captions"
```

- [ ] **Step 2: Run the suite**

Run:
```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_contract.py -v
```
Expected: PASS, 9 tests, all parameterised `[memory]`.

- [ ] **Step 3: Confirm the full suite**

Run:
```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **173 passed, 1 skipped**.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_vector_store_contract.py
git commit -m "test: add vector store contract suite"
```

---

### Task 5: Migration 0002 and the pgvector implementation

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/alembic/versions/0002_transcript_chunks.py`, `backend/app/services/vector_store/postgres.py`
- Modify: `backend/app/services/vector_store/__init__.py`

**Interfaces:**
- Consumes: `VectorStore`, `chunk_to_result` (Task 2); `script.py.mako` (Task 1).
- Produces: `PgVectorStore(session_factory: async_sessionmaker[AsyncSession], embedding_dimensions: int = 1536)`. Task 6 constructs it with a session factory it creates itself.

**Design note — no import from `app.analytics`.** `PgVectorStore` takes a session factory as a constructor argument rather than importing `AsyncSessionLocal` from `app/analytics/database.py`. Vectors are not analytics; reaching into that package would couple two unrelated domains and make the store untestable without it. Phase 2b's factory passes the shared session factory in, so there is still exactly one connection pool.

- [ ] **Step 1: Add the dependency**

Append to `backend/requirements.txt`:

```
pgvector==0.3.6
```

Install:
```bash
cd backend && pip install pgvector==0.3.6
```

- [ ] **Step 2: Write the migration**

Create `backend/alembic/versions/0002_transcript_chunks.py`:

```python
"""transcript chunks with pgvector

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Matches text-embedding-3-small. Changing the embedding provider changes this
# number, which requires a new migration plus a full re-ingest — the same
# constraint CLAUDE.md already documents for the Chroma setup.
EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("create extension if not exists vector")
    op.create_table(
        "transcript_chunks",
        sa.Column("chunk_id", sa.Text(), primary_key=True),
        sa.Column("video_id", sa.Text(), nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("segment_indices", sa.ARRAY(sa.Integer()), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute(
        "create index ix_transcript_chunks_embedding on transcript_chunks "
        "using hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_transcript_chunks_embedding", table_name="transcript_chunks")
    op.drop_table("transcript_chunks")
```

- [ ] **Step 3: Verify the migration compiles offline**

Run:
```bash
cd backend && DATABASE_URL='postgresql+asyncpg://u:p@localhost:5432/db' python -m alembic upgrade head --sql
```
Expected: prints `CREATE TABLE transcript_chunks`, the `create extension` statement and the HNSW index, exit 0. No database is contacted in `--sql` mode.

- [ ] **Step 4: Implement the store**

Create `backend/app/services/vector_store/postgres.py`:

```python
from sqlalchemy import bindparam, delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.chunks import TranscriptChunk
from app.schemas.vectorstore import VectorSearchResult


class PgVectorStore:
    """Transcript chunk storage backed by Postgres + pgvector."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_dimensions: int = 1536,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_dimensions = embedding_dimensions

    async def replace_video_chunks(
        self,
        video_id: str,
        chunks: list[TranscriptChunk],
    ) -> list[str]:
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(f"chunk {chunk.chunk_id} has no embedding")
            if len(chunk.embedding) != self._embedding_dimensions:
                raise ValueError(
                    f"embedding dimension mismatch for {chunk.chunk_id}: "
                    f"{len(chunk.embedding)} != {self._embedding_dimensions}"
                )

        async with self._session_factory() as session:
            # One transaction: a failure part-way leaves the previous chunks intact
            # rather than a video with nothing retrievable.
            async with session.begin():
                await session.execute(
                    text("delete from transcript_chunks where video_id = :video_id"),
                    {"video_id": video_id},
                )
                if chunks:
                    await session.execute(
                        text(
                            "insert into transcript_chunks "
                            "(chunk_id, video_id, chunk_index, text, start_seconds, "
                            " end_seconds, segment_indices, token_estimate, source, "
                            " language, embedding) "
                            "values (:chunk_id, :video_id, :chunk_index, :text, "
                            " :start_seconds, :end_seconds, :segment_indices, "
                            " :token_estimate, :source, :language, :embedding)"
                        ),
                        [
                            {
                                "chunk_id": chunk.chunk_id,
                                "video_id": chunk.video_id,
                                "chunk_index": chunk.index,
                                "text": chunk.text,
                                "start_seconds": chunk.start_seconds,
                                "end_seconds": chunk.end_seconds,
                                "segment_indices": chunk.segment_indices,
                                "token_estimate": chunk.token_estimate,
                                "source": str(chunk.metadata.get("source", "")) or None,
                                "language": str(chunk.metadata.get("language", "")) or None,
                                "embedding": str(chunk.embedding),
                            }
                            for chunk in chunks
                        ],
                    )

        return [chunk.chunk_id for chunk in chunks]

    async def similarity_search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        video_id: str | None = None,
    ) -> list[VectorSearchResult]:
        statement = text(
            "select chunk_id, video_id, text, start_seconds, end_seconds, "
            "       segment_indices, source, language, "
            "       embedding <=> :query_embedding as distance "
            "from transcript_chunks "
            "where (:video_id::text is null or video_id = :video_id) "
            "order by embedding <=> :query_embedding "
            "limit :limit"
        )

        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    statement,
                    {
                        "query_embedding": str(query_embedding),
                        "video_id": video_id,
                        "limit": limit,
                    },
                )
            ).mappings().all()

        return [
            VectorSearchResult(
                chunk_id=row["chunk_id"],
                video_id=row["video_id"],
                text=row["text"],
                start_seconds=row["start_seconds"],
                end_seconds=row["end_seconds"],
                segment_indices=list(row["segment_indices"] or []),
                distance=float(row["distance"]),
                metadata={
                    key: value
                    for key, value in (
                        ("source", row["source"]),
                        ("language", row["language"]),
                    )
                    if value is not None
                },
            )
            for row in rows
        ]
```

Update `backend/app/services/vector_store/__init__.py`:

```python
from app.services.vector_store.base import VectorStore, chunk_to_result, cosine_distance
from app.services.vector_store.memory import InMemoryVectorStore
from app.services.vector_store.postgres import PgVectorStore

__all__ = [
    "InMemoryVectorStore",
    "PgVectorStore",
    "VectorStore",
    "chunk_to_result",
    "cosine_distance",
]
```

- [ ] **Step 5: Verify imports and the untouched suite**

Run:
```bash
cd backend && python -c "from app.services.vector_store import PgVectorStore; print('ok')"
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: prints `ok`; suite still **173 passed, 1 skipped** (no new tests yet — Task 6 adds the pgvector parameterisation).

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/alembic/versions/0002_transcript_chunks.py backend/app/services/vector_store
git commit -m "feat: add pgvector store and transcript_chunks migration"
```

---

### Task 6: Run the contract suite against pgvector

This is the task that earns the right to delete Chroma in Phase 2b: it proves both implementations satisfy the same contract.

**Files:**
- Modify: `backend/tests/test_vector_store_contract.py`

**Interfaces:**
- Consumes: `PgVectorStore` (Task 5), `InMemoryVectorStore` (Task 3), the `store` fixture (Task 4).
- Produces: nothing new. Test bodies from Task 4 must remain byte-identical — only the fixture changes.

**The dimension problem, and why the fixture looks like it does.** The contract tests use 3-dimensional vectors because `[1.0, 0.0, 0.0]` is readable and its cosine distances are checkable by hand. The production column is `vector(1536)`. Rather than rewrite every test with 1536-element vectors — which would make the assertions unreadable and prove nothing extra — the fixture narrows the column to `vector(3)` for the duration of the pgvector run and restores it afterwards. `TEST_DATABASE_URL` must therefore never point at production.

- [ ] **Step 1: Replace the imports and the `store` fixture**

In `backend/tests/test_vector_store_contract.py`, replace the imports and the `store` fixture with the following. Leave every test body byte-identical.

```python
import os

import pytest

from app.schemas.chunks import TranscriptChunk
from app.services.vector_store import InMemoryVectorStore, PgVectorStore

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

BACKENDS = ["memory"]
if TEST_DATABASE_URL:
    BACKENDS.append("pgvector")

# The contract vectors are 3-dimensional for readability; production is 1536.
# The pgvector fixture narrows the column for the run and restores it after.
CONTRACT_DIMENSIONS = 3
PRODUCTION_DIMENSIONS = 1536


@pytest.fixture(params=BACKENDS)
async def store(request):
    """Yield each backend in turn.

    WARNING: the pgvector branch mutates the transcript_chunks schema and deletes
    all its rows. TEST_DATABASE_URL must never point at a production database.
    """
    if request.param == "memory":
        yield InMemoryVectorStore()
        return

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        async with session.begin():
            # Each test starts empty: the contract asserts ordering and isolation,
            # which leftover rows would silently break.
            await session.execute(text("delete from transcript_chunks"))
            await session.execute(
                text(
                    "alter table transcript_chunks "
                    f"alter column embedding type vector({CONTRACT_DIMENSIONS})"
                )
            )

    try:
        yield PgVectorStore(factory, embedding_dimensions=CONTRACT_DIMENSIONS)
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(text("delete from transcript_chunks"))
                await session.execute(
                    text(
                        "alter table transcript_chunks "
                        f"alter column embedding type vector({PRODUCTION_DIMENSIONS})"
                    )
                )
        await engine.dispose()
```

The `try/finally` matters: without it a failing assertion leaves the column at `vector(3)`, and every later run — including a production migration — behaves strangely for reasons the failure message will not explain.

- [ ] **Step 2: Verify the skip path still works**

Run without a database:
```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_contract.py -v
```
Expected: **9 passed**, all `[memory]`. No errors, no skips — the pgvector params simply are not generated.

- [ ] **Step 3: Verify the full suite is unchanged**

Run:
```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **173 passed, 1 skipped**.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_vector_store_contract.py
git commit -m "test: run the vector store contract against pgvector when available"
```

---

### Task 7: Live verification against Supabase

Requires the operator's database credentials. An agent cannot run this task.

**Files:** none modified. Verification only.

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: confirmation that migration `0002` applies and both implementations satisfy the contract against real pgvector.

- [ ] **Step 1: Apply migration 0002**

```bash
cd backend
$env:DATABASE_URL = "<the Supabase connection string, port 5432>"
& "C:\Program Files\Python312\python.exe" -m alembic upgrade head
```
Expected: `Running upgrade 0001 -> 0002, transcript chunks with pgvector`.

If it fails with `extension "vector" is not available`, enable it in the Supabase dashboard under Database → Extensions → `vector`, then retry.

- [ ] **Step 2: Run the contract suite against real pgvector**

```bash
$env:TEST_DATABASE_URL = $env:DATABASE_URL
& "C:\Program Files\Python312\python.exe" -m pytest tests/test_vector_store_contract.py -v
```
Expected: **18 passed** — every test twice, once per backend. This is the evidence that the two implementations behave identically.

- [ ] **Step 3: Confirm the table and index exist**

In the Supabase dashboard → Table Editor, confirm `transcript_chunks` is present with an `embedding` column of type `vector`.

- [ ] **Step 4: Record the result**

Append the outcome to `LEARNINGS.md` if anything surprising surfaced — particularly if the `vector` extension needed manual enabling, since that is not obvious from the migration alone.

---

## What this plan deliberately does not do

Nothing here is wired into the application. `ChromaVectorStoreService` remains the only store any route, service or tool uses, and every existing test is untouched.

**The spec's error-handling requirements are deferred to Phase 2b, not dropped.** The design mandates that retrieval failures return a loud 502 and that a paused Supabase project produces a message naming the cause and the fix. Neither belongs here: this plan creates no request path, so there is no HTTP boundary to map an exception onto, and a store raising a plain exception is the correct behaviour for a component with no knowledge of FastAPI. The mapping lands with the consumers.

What this plan *does* implement from that section is the dimension-mismatch requirement: `cosine_distance` and `PgVectorStore.replace_video_chunks` both raise `ValueError` with the offending sizes named, rather than surfacing a raw database type error. Task 2 asserts it.

**Phase 2b** performs the cutover:

- repurpose `vectorstore_service.py` as the embedding orchestrator delegating to an injected `VectorStore`
- add the factory with the derived default (`DATABASE_URL` set → pgvector, else memory)
- update the 9 `ChromaVectorStoreService` type annotations across `rag_service.py`, `agent_service.py`, `api/routes/vectorstore.py`, `tools/__init__.py`, `tools/retrieve_context.py`, `tools/store_video_vectors.py`, `tools/ingest_video.py`
- rewrite the existing Chroma-backed tests against the protocol
- verify live: ingest a video, ask a question, confirm citations resolve and survive a restart
- **only then** delete `ChromaVectorStoreService` and `chromadb==1.3.7`

Splitting there is deliberate: the cutover swaps a component that this plan has already proven works, rather than swapping and proving at once.
