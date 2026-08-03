# Phase 2b: cut retrieval over to pgvector — design

- **Date:** 2026-08-03
- **Branch:** `phase2b/vector-cutover`
- **Status:** Approved design, not yet planned or implemented
- **Predecessors:** Phase 1 (`60c353c`) analytics on Postgres; Phase 2a (`bc93080`) vector store subsystem, verified against live pgvector (18 contract tests, 9 per backend)

## Problem

Phase 2a built and proved a `VectorStore` protocol with in-memory and pgvector
implementations. Nothing consumes it. `ChromaVectorStoreService` is still the only
store the application uses, so transcript vectors still live in the API process and
still vanish on every Render restart.

This phase connects the proven component and removes the old one.

## What makes this the riskiest phase

Every prior phase was reversible or invisible:

- Phase 1 touched analytics, which is fire-and-forget — a failed write is swallowed.
- Phase 2a was purely additive: 12 files, +1885/−0, no existing line modified.

This phase changes the **request path**. Retrieval is the product: a failure means
either an error or, worse, an ungrounded answer from an app whose promise is
transcript-grounded citations. There is no swallow-and-continue cushion.

That is why the rollout is staged rather than direct.

## Decisions taken during brainstorming

### 1. The orchestrator keeps the existing method names

Reading the call sites showed every one of them calls `.upsert_chunks(chunks)` or
`.similarity_search(query, limit, video_id)`. If the new `VectorStoreService` keeps
those exact signatures and delegates internally, then **all nine call sites change
only their type annotation** — not one call expression.

That reduces the cutover to a rename plus one new class, which is a materially
smaller change than rewriting nine call sites, and it keeps the diff reviewable.

Internally the orchestrator does the two things Chroma did inline: generate
embeddings, then delegate persistence to the injected `VectorStore`.
`upsert_chunks` derives `video_id` from the chunks — every call site passes one
video's chunks — and calls `store.replace_video_chunks`, which is where Phase 2a's
stale-chunk fix actually takes effect.

### 2. Staged rollout: Chroma stays the default until pgvector is verified in production

The Phase 2 spec's derived default (`DATABASE_URL` set → pgvector) would mean merging
the cutover switches production retrieval immediately, making the first real request
after deploy also the first test of the wired path.

Instead the factory resolves:

```
VECTOR_BACKEND explicit    → that backend
otherwise, Chroma present  → chroma                                  (this phase)
otherwise                  → DATABASE_URL set ? pgvector : memory    (after deletion)
```

So merging changes nothing. Production flips by setting one variable on Render, and
rolls back by unsetting it. The derived default — and the silent-amnesia protection
that motivated it — arrives in the second step, once Chroma is gone and there is no
longer a safe fallback to default to.

### 3. `VECTOR_COLLECTION_NAME` replaces `CHROMA_COLLECTION_NAME`

`collection_name` is a ChromaDB concept baked into the public API: it appears in
`IngestVideoResponse` and `VectorSearchResponse`, is populated from
`settings.chroma_collection_name` at three route handlers, is declared in
`frontend/lib/api.ts` and asserted in a frontend test. pgvector has no collections —
only a table.

The field stays (schemas and frontend are unchanged), but the setting behind it is
renamed to `VECTOR_COLLECTION_NAME`, default `asktube_videos`, with
`CHROMA_COLLECTION_NAME` kept as a fallback alias so the existing Render environment
keeps working without edits. The name stops referring to a backend that will not
exist.

## Goals

1. Retrieval and ingestion run through the `VectorStore` protocol.
2. Transcript vectors survive Render restarts.
3. ChromaDB and `chromadb==1.3.7` are gone.
4. Public API contract, response schemas and the frontend unchanged.
5. Deployment stays at **$0/month**.

## Non-goals

- Conversation memory (Phase 3).
- Consolidating the agent and RAG answer paths.
- Retrieval quality work: reranking, hybrid search, tuning `top_k`.
- Any frontend change.

## Architecture

`app/services/vectorstore_service.py` keeps its module path and gains
`VectorStoreService`, replacing `ChromaVectorStoreService`:

```python
class VectorStoreService:
    def __init__(self, config: Settings, store: VectorStore) -> None: ...

    async def upsert_chunks(self, chunks: list[TranscriptChunk]) -> list[str]:
        """Embed any chunk missing an embedding, then replace that video's chunks."""

    async def similarity_search(
        self, query: str, limit: int = 5, video_id: str | None = None
    ) -> list[VectorSearchResult]:
        """Embed the query, then delegate to the store."""
```

Signatures match today's `ChromaVectorStoreService` exactly, so call sites need only
their annotation changed.

**Deriving `video_id`, precisely.** `upsert_chunks` takes chunks but the store's
`replace_video_chunks` needs a video. Three cases, all explicit:

- **Empty list → return `[]` and touch nothing.** It must NOT clear a video, because
  there is no video named. Today's Chroma `upsert` on an empty list is likewise a
  no-op, so this preserves behaviour. Clearing a video is expressed by calling the
  store directly, not by passing an empty list here.
- **All chunks share one `video_id` → replace that video's chunks.** The normal path.
- **Chunks span multiple videos → raise `ValueError` naming the ids found.** No call
  site does this, and silently replacing only the first video's chunks — or worse,
  deleting one video's chunks while inserting another's — would be a data-loss bug
  that no test would catch. Failing loudly is correct for a case that cannot legitimately
  occur.

`get_vectorstore_service()` keeps its name and is the FastAPI dependency; it builds
the service with the store from `create_vector_store(settings)`. The existing
`app.dependency_overrides[get_vectorstore_service]` in two test modules keeps working.

The nine annotation sites:

| File | Sites |
|---|---|
| `app/services/rag_service.py` | import, constructor param, factory call |
| `app/services/agent_service.py` | import, `get_vectorstore_service()` call |
| `app/api/routes/vectorstore.py` | import + 4 `Depends` annotations |
| `app/tools/__init__.py` | import + construction |
| `app/tools/retrieve_context.py` | import + `make_retrieve_context_tool` param |
| `app/tools/store_video_vectors.py` | import + `make_store_video_vectors_tool` param |
| `app/tools/ingest_video.py` | import + param |

## Error handling

- **Retrieval or ingest failure → 502, loudly.** No degradation. An ungrounded answer
  is worse than an error for this product.
- **Paused-database hint.** Deferred from Phase 1 because analytics never surfaced a
  connection error to a user; this is the first request path that does. Following the
  precedent of commit `b1e3a3d` (which turned YouTube's IP block into a clean 502
  carrying a proxy hint), a connection failure returns a message naming the likely
  cause and the fix.
- **Dimension mismatch → explicit error** naming the offending sizes, already
  implemented in Phase 2a's store and surfaced here as a 502 rather than a raw
  database error.

## Testing

Existing tests that fake the store are rewritten against the new interface:

- `tests/test_vectorstore_route.py` — `FakeVectorStoreService` gains the new signatures
- `tests/test_ingest_stream.py` — the `get_vectorstore_service` override
- any `test_vectorstore_service.py` assertions tied to Chroma internals

The Phase 2a contract suite is untouched and continues to prove both implementations
behave identically. The orchestrator gets its own tests for what only it does:
embedding generation for chunks missing embeddings, deriving `video_id` from chunks,
and rejecting a call whose chunks span more than one video.

`tests/test_tools.py` and the agent tests exercise the tool layer through the new
annotations.

## Cutover

**Step 2b-i — the cutover, inert.**
Orchestrator, factory defaulting to Chroma, nine annotations, rewritten tests.
Merges safely: production still uses Chroma, and the only observable change is that
ingestion now replaces a video's chunks instead of upserting them.

**Verification gate (operator, requires credentials).**
Set `VECTOR_BACKEND=pgvector` on Render. Then: ingest a video, ask a question, confirm
the timestamped citations resolve, **restart the service**, and confirm the chunks are
still retrievable without re-ingesting. That last check is the entire point of the
project — it is the first time AskTube AI's retrieval survives a restart.
Rollback is unsetting the variable.

**Step 2b-ii — the flip.**
Change the factory default to derived (`DATABASE_URL` set → pgvector), delete
`ChromaVectorStoreService`, remove `chromadb==1.3.7` from `requirements.txt`, and drop
the dead `CHROMA_*` settings apart from the `CHROMA_COLLECTION_NAME` fallback alias.

Deleting last is deliberate: until pgvector has served real production traffic, Chroma
is the rollback.

## Definition of done

- `cd backend && python -m pytest` → all green, skip semantics unchanged
- `cd frontend && npx tsc --noEmit && npm test` → **79 passed**
- Live: a video ingested before a Render restart is still answerable after it
- `chromadb` absent from `requirements.txt`; no import of it anywhere
- Render image smaller than before (worth measuring, not worth blocking on)

## Open risks

**Ingestion semantics change on merge of 2b-i.** Even with Chroma as the default, the
orchestrator calls `replace_video_chunks`, so re-ingesting a video now deletes its old
chunks first. That is the intended bug fix, but it is a live behaviour change arriving
one step earlier than the backend switch. It is safe — re-ingest already produced the
correct chunk set; only the stale leftovers disappear.

**The `metadata` round-trip narrows.** Chroma stored arbitrary scalar metadata;
`transcript_chunks` has typed `source` and `language` columns. Any other metadata key
a chunk carries is dropped by the pgvector store. Nothing in the codebase reads other
keys today, but a future chunker adding one would lose it silently.
