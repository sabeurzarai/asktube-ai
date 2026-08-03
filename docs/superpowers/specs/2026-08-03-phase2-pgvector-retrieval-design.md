# Phase 2: transcript vectors on pgvector — design

- **Date:** 2026-08-03
- **Branch:** `phase2/pgvector-retrieval`
- **Status:** Approved design, not yet planned or implemented
- **Predecessor:** Phase 1 (`60c353c`) — analytics on managed Postgres, merged and verified live

## Problem

ChromaDB runs embedded in the API process (`CHROMA_USE_HTTP=false`) and Render's free
tier has no persistent disk, so every deploy and every idle-sleep wipes all transcript
vectors. The documented workaround is to re-ingest a demo video before presenting.

Two further consequences:

- The process cannot scale past one worker — each would hold its own vector store.
- `ChromaVectorStoreService` is referenced concretely by `rag_service.py`, the
  vectorstore routes and three tools, so replacing it means editing every call site.

Phase 1 moved analytics to Postgres and proved the connection stack end to end. This
phase moves the vectors onto the same database.

## What makes this phase riskier than Phase 1

Phase 1 touched a fire-and-forget path: a failed analytics write was swallowed by
`safe_track_background` and nothing user-facing broke. Retrieval has no such safety
net — it *is* the product. A failure means either an error or, worse, an ungrounded
answer from an app whose entire promise is transcript-grounded citations.

The surface is also wider: `vectorstore_service.py`, `rag_service.py`, the vectorstore
routes, and the `tools/` layer (`retrieve_context`, `store_video_vectors`,
`ingest_video`) that the agent calls.

## Decisions taken during brainstorming

1. **ChromaDB is replaced, not kept.** The protocol is a migration seam, not a
   permanent abstraction. Once pgvector is verified against the live database,
   `ChromaVectorStoreService` and `chromadb==1.3.7` are deleted — which also removes a
   heavy dependency from the Render image.
2. **An in-memory implementation takes over local dev and CI.** Chroma is currently
   serving, accidentally, as the test double that lets ~25 vectorstore and tool tests
   run with zero infrastructure. Removing it without a replacement would make the suite
   require a live database. The replacement is deliberate and purpose-built.
3. **Re-ingest replaces a video's chunks** rather than upserting by `chunk_id`. This
   fixes a latent bug that predates this work (see below).

### The stale-chunk bug being fixed

`vectorstore_service.py` calls `collection.upsert(ids=chunk_ids)`. Chunk IDs derive
from the chunking parameters, so re-ingesting a video after `CHUNK_MAX_CHARS` changes
produces new IDs and leaves the old chunks in place forever. Retrieval then mixes two
different chunkings of the same video, and nothing ever cleans them up. Porting to SQL
is the natural moment to fix it, because it is the difference between writing
`ON CONFLICT DO UPDATE` and writing a delete-then-insert.

## Goals

1. Transcript vectors survive Render restarts.
2. One storage backend in production, one purpose-built double for tests.
3. Retrieval behaviour — ordering, distance scale, filtering — unchanged.
4. Public API contract, response schemas and the frontend untouched.
5. Deployment stays at **$0/month**.

## Non-goals

- Conversation memory (Phase 3).
- Consolidating the agent and RAG answer paths.
- Changing chunking, the embedding provider switch, or the LLM provider switch.
- Retrieval quality work (reranking, hybrid search, tuning `top_k`).

## Architecture

A package, not a fourth flat module. Phase 1 kept things flat because it touched one
file; three implementations plus a protocol is where that stops working.

```
app/services/vector_store/
├── base.py       VectorStore protocol + shared result parsing
├── memory.py     in-memory implementation (dev/CI)
├── postgres.py   pgvector implementation
└── factory.py    create_vector_store(settings) — VECTOR_BACKEND switch
```

`factory.py` mirrors the existing `llm_provider.py` / `embedding_provider.py` factory
idiom, so the pattern is already familiar in this codebase.

### The protocol

Derived from what the code actually does, not from Chroma's API:

```python
async def replace_video_chunks(video_id: str, chunks: list[TranscriptChunk]) -> list[str]
async def similarity_search(
    query_embedding: list[float],
    limit: int,
    video_id: str | None,
) -> list[VectorSearchResult]
```

Two deliberate departures from `ChromaVectorStoreService`:

**`replace_video_chunks` rather than `upsert_chunks`.** Both ingest routes supply the
complete chunk set for exactly one video, so a single replace-semantics method covers
every call site — and it is the fix for the stale-chunk bug. One method, rather than an
`upsert` plus a `replace` with overlapping meaning.

**`similarity_search` takes an embedding, not a query string.** Today the store calls
`aembed_query` internally. Left that way, the in-memory and Postgres implementations
would each duplicate embedding logic and could drift. Hoisting it into a thin
`VectorSearchService` above the store means the embedding path exists once, the store
implementations do exactly one job, and the in-memory implementation is testable
without an OpenAI key.

### Where the orchestrator lives

`vectorstore_service.py` keeps its module path and is repurposed as the thin
orchestrator: it generates embeddings and delegates storage and retrieval to the
injected `VectorStore`. It stops containing any Chroma-specific code.

Keeping the filename is deliberate. `get_vectorstore_service()` is imported by
`rag_service.py`, the routes and three tools; repurposing the module rather than
introducing a parallel `vector_search_service.py` keeps those imports stable and avoids
a period where two similarly named services coexist and reviewers must guess which is
authoritative.

So the split is: `app/services/vectorstore_service.py` owns embeddings and
orchestration; `app/services/vector_store/` owns persistence only.

### Consumers

`rag_service.py`, the vectorstore routes and the three tools continue to call
`get_vectorstore_service()`. Their call shapes barely change — this is a seam swap
behind a stable module boundary, not a rewrite.

## Data model

### Migration `0002` (`down_revision = "0001"`)

```sql
create extension if not exists vector;

create table transcript_chunks (
  chunk_id        text primary key,
  video_id        text not null,
  chunk_index     integer not null,
  text            text not null,
  start_seconds   double precision not null,
  end_seconds     double precision not null,
  segment_indices integer[] not null,
  token_estimate  integer not null,
  source          text,
  language        text,
  embedding       vector(1536) not null,
  created_at      timestamptz default now()
);

create index on transcript_chunks using hnsw (embedding vector_cosine_ops);
create index on transcript_chunks (video_id);
```

`segment_indices` is a native `integer[]`. Today `to_chroma_metadata` calls
`json.dumps` on write and `parse_segment_indices` parses it back on read, purely
because Chroma metadata cannot hold lists. Both helpers are deleted by this change.

This phase also closes Phase 1's deferred gap: `backend/alembic/script.py.mako` does
not exist, so `alembic revision` fails with `TemplateNotFound`. It is a task here, not
an afterthought.

### Distance semantics

pgvector's `<=>` operator and Chroma's `hnsw:space: cosine` both compute
`1 − cosine_similarity`. `VectorSearchResult.distance` therefore keeps the same meaning
and scale, and the evaluation thresholds in `observability_service.py` do not silently
shift. Using `<->` (L2) instead would produce numbers that look plausible and mean
something different — the kind of change that passes tests and corrupts judgement.

### Query

```sql
select chunk_id, video_id, text, start_seconds, end_seconds,
       segment_indices, embedding <=> :q as distance
from transcript_chunks
where (:video_id::text is null or video_id = :video_id)
order by embedding <=> :q
limit :k
```

### Replace, transactionally

Delete by `video_id`, then insert, inside one transaction. A mid-ingest failure rolls
back and leaves the previous chunks intact, so a video never ends up with zero
retrievable chunks because an embedding call timed out halfway through.

### Embedding dimension

`vector(1536)` matches `text-embedding-3-small`. The `EMBEDDING_PROVIDER=local` path
uses all-MiniLM-L6-v2 at 384 dimensions, and one column cannot serve both. The
dimension is a migration-time setting; switching providers requires wiping and
re-ingesting. This constrains nothing new — `CLAUDE.md` already documents exactly that
requirement for the current Chroma setup.

## The in-memory implementation

A dict keyed by `video_id` plus cosine similarity computed in **pure Python** — dot
product over norms, roughly ten lines.

Deliberately not numpy: `numpy` is not in `requirements.txt`, it arrives transitively
via `chromadb`, and `chromadb` is being deleted. Reaching for numpy here would quietly
re-add a dependency we just removed, in order to serve a test double.

## The default-backend hazard

Phase 1's flags defaulted to current behaviour, which was safe because the old backend
still existed. Here the old backend is being deleted, so a fixed `VECTOR_BACKEND=memory`
default would mean: forget the variable on Render and production silently runs an
in-memory store that resets on every restart — strictly worse than today, and it would
appear to work.

**The default is derived, not fixed:**

- `DATABASE_URL` set → `pgvector`
- otherwise → `memory`
- explicit `VECTOR_BACKEND` overrides both

Production already carries `DATABASE_URL` from Phase 1, so it gets pgvector
automatically; a bare checkout gets the in-memory store and needs no infrastructure.
The failure mode becomes a loud error about a missing database rather than silent
amnesia.

## Error handling

- **Retrieval failure → fail loudly (502).** No degradation. An ungrounded answer is
  worse than an error for a product promising transcript-grounded citations.
- **Paused-database message.** Phase 1 deferred this because analytics is
  fire-and-forget and never surfaced a connection error to a user. This is the first
  request path that does, so the message lands here, following the precedent of commit
  `b1e3a3d` (which turned YouTube's IP block into a clean 502 carrying a proxy hint):
  connection failure returns a message naming the likely cause and the fix.
- **Dimension mismatch → explicit error**, not a raw database type error.

## Testing

One contract suite asserting behaviour, parameterised over both implementations:

- store then retrieve returns the chunk
- `video_id` filtering isolates videos
- results are ordered by ascending distance
- re-ingest **replaces** rather than accumulates (the bug fix, asserted)
- dimension mismatch raises a clear error

In-memory runs everywhere; the pgvector parameterisation skips unless
`TEST_DATABASE_URL` is set, matching the convention Phase 1 established.

The ~25 existing Chroma tests are rewritten against the protocol rather than deleted.
**The contract suite is what makes deleting Chroma safe** — it proves the replacement
behaves identically before the original is removed.

## Cutover

1. Protocol, in-memory implementation, contract suite. No behaviour change yet.
2. pgvector implementation + migration `0002` + `script.py.mako`.
3. Switch consumers to the injected store; derived backend default.
4. Verify against the live database (requires the operator's credentials).
5. **Only then** delete `ChromaVectorStoreService` and `chromadb` from
   `requirements.txt`.

Step 5 is last on purpose. Deleting the old implementation before the new one is proven
against a real database would leave no fallback.

**Nothing to migrate:** production Chroma data is ephemeral today, so there is no
export or backfill — deploy, re-ingest, done.

## Definition of done

- `cd backend && python -m pytest` → all green, skip semantics unchanged
  (pgvector tests skip without `TEST_DATABASE_URL`)
- `cd frontend && npx tsc --noEmit && npm test` → **79 passed**
- Live verification: ingest a video against Postgres, ask a question, confirm the
  timestamped citations resolve and the chunks survive a service restart
- `chromadb` absent from `requirements.txt`; no import of it anywhere

## Open items

**Render image size.** Removing `chromadb` should shrink the image and speed builds.
Worth measuring before and after, but not worth blocking on.

**HNSW tuning.** The index is created with pgvector defaults (`m`, `ef_construction`).
At a few thousand chunks this is comfortably adequate. Revisit only if retrieval
latency is ever measured as the bottleneck — which Phase 1's evidence suggests it will
not be, since embedding and generation dominate.
