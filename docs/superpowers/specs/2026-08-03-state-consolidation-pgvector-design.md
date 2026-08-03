# State consolidation onto Postgres + pgvector — design

- **Date:** 2026-08-03
- **Branch:** `arch/state-consolidation-pgvector`
- **Status:** Approved design, not yet planned or implemented

## Problem

The backend keeps three separate state stores, and all three live inside the API
process:

| Store | Lives in | Survives restart? |
|---|---|---|
| Vectors | ChromaDB embedded in the process (`CHROMA_USE_HTTP=false`) | No |
| Analytics | SQLite file in the container | No |
| Chat memory | Python `dict` in `app/services/memory_service.py` | No |

Render's free tier has no persistent disk and restarts on every deploy and after
idle sleep. Every restart therefore wipes the vector store, the analytics history
and every conversation. The documented workaround is to re-ingest a demo video
before presenting (`DEMO_DAY_RUNBOOK.md` step 0).

Two consequences beyond the data loss:

- The process cannot be scaled to more than one worker. Memory is per-process, so
  a second worker would answer follow-up questions with no conversation history.
- Storage choices are wired into call sites. `ChromaVectorStoreService` is
  referenced concretely, so replacing it means editing every caller.

## Goals

1. Make the API process stateless — no durable state inside the container.
2. Survive Render restarts without re-ingesting.
3. Keep the deployment at **$0/month**.
4. Leave the public API contract and the entire frontend unchanged.

## Non-goals

- Changing the embedding or LLM providers. OpenAI embeddings and Whisper stay;
  the `LLM_PROVIDER` switch stays.
- Consolidating the agent and RAG answer paths. That is a separate piece of work
  (see "Sequencing context").
- Splitting the deployment into multiple services.
- Any frontend change.

## Constraints

- **Strictly $0/month.** Rules out paid Render disks and managed vector databases.
- **Supabase Free auto-pauses** a project after 7 days of low activity. Restoring
  is a manual action (dashboard, or `POST /v1/projects/{ref}/restore`). A project
  paused for more than 90 days is deleted permanently. Verified against Supabase
  docs on 2026-08-03; the pre-existing `neuraflow` project in the same org was
  already paused, which is what surfaced the issue.
- **No backups** on the free tier. Postgres is therefore not a system of record:
  everything in it must remain reproducible by re-ingesting videos.
- Push to `main` auto-deploys both Vercel and Render, so every step must leave the
  app deployable.

## Approach

**Chosen: consolidate all three stores into one free managed Postgres with the
`pgvector` extension.** One dependency, one connection pool, one place where state
lives. The API process becomes disposable.

Provisioned during design: Supabase project `asktube-ai`
(ref `yskjultqsrbikvmyvwnu`), org Zarai, region `eu-west-3` (Paris), NANO compute,
free plan, Data API disabled, no repository linked.

### Alternatives rejected

- **Best-of-breed free services** (Qdrant Cloud + Neon + Upstash Redis). Three
  external dependencies, three credential sets, three free-tier policies, for a
  dataset that `pgvector` handles comfortably (~3,000 chunks ≈ 20 MB against a
  500 MB ceiling). The right architecture at a scale this project does not have.
- **Stay ephemeral and engineer around it** (boot-time re-ingest of a demo video).
  Smallest change and it would make demos reliable, but it is a workaround rather
  than an architecture: the app still cannot run two workers and state still resets.

### Region note

The Supabase form advises picking the region closest to your users. That is the
wrong optimisation here — users talk to Vercel, and the database's only client is
the Render backend. Paris was chosen; if Render runs in Frankfurt the extra hop is
roughly 10 ms, which is noise against embedding and LLM latency. Not worth
rebuilding the project. Revisit only if retrieval is ever measured as the bottleneck.

## Architecture

```
BEFORE                                  AFTER
┌──────────────────────────┐            ┌─────────────────┐
│ FastAPI process (Render) │            │ FastAPI (Render)│  stateless
│  ├── ChromaDB (embedded) │            │  └── SQLAlchemy │  ── async pool ──┐
│  ├── SQLite analytics    │            └─────────────────┘                  │
│  └── memory dict         │                                                 ▼
└──────────────────────────┘                                    ┌────────────────────────┐
   all lost on restart                                          │ Postgres (Supabase)    │
                                                                │  ├── chunks + pgvector │
                                                                │  ├── analytics tables  │
                                                                │  └── conversations     │
                                                                └────────────────────────┘
```

Three boundaries keep this testable and reversible:

1. **`VectorStore` protocol** — a narrow interface (`upsert_chunks`,
   `similarity_search`) with two implementations, the existing Chroma one and a new
   pgvector one, selected by a `VECTOR_BACKEND` setting. This mirrors the existing
   `llm_provider.py` / `embedding_provider.py` factory pattern, so it is idiomatic
   in this codebase rather than a new concept. Chroma keeps working, local
   development needs no database, and the existing vectorstore tests keep passing.
2. **`ConversationStore` protocol** — behind today's `ConversationMemoryService`,
   with an in-process implementation for tests and a Postgres one for deployment.
3. **Startup-scoped clients** — the Chroma/pgvector client and the embedding client
   move from per-request construction into the FastAPI `lifespan` and reach routes
   via `Depends`. Today `similarity_search` calls `get_collection()` on every query,
   constructing a fresh `chromadb.PersistentClient` per request.

Unchanged: OpenAI embeddings and Whisper, the LLM provider switch, every API route
and response schema, and the whole frontend.

## Data model

There is **no data to migrate**. Nothing is durable today, so there is no export,
no backfill and no dual-write window: create empty tables and re-ingest. This will
not be true again once Postgres holds real history.

### Analytics

`app/analytics/models.py` is already SQLAlchemy `DeclarativeBase`, so this is
largely a connection-string change on `ANALYTICS_DATABASE_URL`. Two adjustments:

- `JSON` columns become `JSON().with_variant(JSONB, "postgresql")` so
  `metadata_json` is indexable.
- `DateTime(timezone=True)` starts genuinely storing timezones; SQLite silently
  discards them today, so this is a quiet correctness improvement.

`String(36)` UUID primary keys stay as text. Native `UUID` would be tidier but
changes nothing functionally.

### Vectors

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

Cosine distance matches Chroma's `hnsw:space: cosine`, preserving retrieval
behaviour rather than silently changing it.

`segment_indices` becomes a native `integer[]`. Today `to_chroma_metadata` calls
`json.dumps` on write and `parse_segment_indices` parses it back on read, purely
because Chroma metadata cannot hold lists. Both helpers are deleted by this change.

**Fixed-dimension trade-off.** `vector(1536)` matches
`text-embedding-3-small`, but the `EMBEDDING_PROVIDER=local` path uses
all-MiniLM-L6-v2 at 384 dimensions, and one column cannot serve both. The dimension
becomes a migration-time setting, and switching embedding providers requires
wiping and re-ingesting. This constrains nothing new: `CLAUDE.md` already documents
exactly that requirement for the current Chroma setup.

### Conversations

```sql
create table conversation_messages (
  id          bigserial primary key,
  session_id  text not null,
  role        text not null,
  content     text not null,
  created_at  timestamptz default now()
);
create index on conversation_messages (session_id, created_at desc);
```

The 8-message window becomes `order by created_at desc limit 8`, reversed.

**Breaking change.** `get_messages` and `append_exchange` are synchronous today and
called without `await` throughout `rag_service.py` and `agent_service.py`. A
Postgres-backed store must be async, so the `ConversationStore` protocol is async on
*both* implementations — including the in-process one, to keep them
interchangeable — and every call site changes. Mechanical, but it touches more files
than the other two pieces combined.

### Schema management

Alembic, not `create_all`. This is not a stylistic preference: `create_all` cannot
express `CREATE EXTENSION vector` or an HNSW index, and the embedding dimension
needs a versioned home.

## Cutover plan

Three independently shippable steps, each behind its own flag, each leaving the app
deployable:

1. **Analytics → Postgres.** Lowest blast radius, and it validates the whole
   connection stack (pooler, SSL, asyncpg settings) on a path where failure cannot
   break chat.
2. **Vectors → pgvector**, behind `VECTOR_BACKEND=chroma|pgvector`.
3. **Memory → Postgres**, behind `MEMORY_BACKEND=memory|postgres`, carrying the
   async refactor.

Both new flags **default to current behaviour** — `VECTOR_BACKEND=chroma` and
`MEMORY_BACKEND=memory` — so merging the code changes nothing until the environment
opts in. Local development and the test suite run on the defaults and need no
database. Production moves one flag at a time, and rollback is reverting a flag
rather than reverting code.

The order is deliberate. If the Supavisor transaction pooler requires
`statement_cache_size=0`, that surfaces in step 1 on the analytics path rather than
mid-demo in the chat path.

## Error handling and failure modes

Moving state out of the process converts three impossible failures into three likely
ones. They get different answers:

- **Analytics unavailable → ignore silently.** Already correct in the codebase:
  `track_event_safe` / `safe_track_background` make analytics fire-and-forget and
  `main.py` catches init failure with a warning. Postgres must not change this. A
  failed metrics write must never turn a working answer into a 500.
- **Vector store unavailable → fail loudly.** Retrieval is the product; an answer
  without transcript context would be ungrounded, which is what this app promises
  not to produce. Keep the existing 502 mapping.
- **Conversation memory unavailable → degrade, do not fail.** Answer with an empty
  memory window rather than refusing. Losing follow-up context is a mild quality
  regression; refusing to answer is an outage. This is a new property — memory
  cannot fail today — so it gets an explicit test.

**Paused-database error.** A paused Supabase project fails as a connection error
that reads like a network fault. Left generic it surfaces as an opaque 502.
Following the precedent of commit `b1e3a3d` (which turned YouTube's IP block into a
clean 502 carrying a proxy hint), connection failure returns a message naming the
likely cause and the fix: "database unreachable — a paused Supabase project must be
restored".

**Connection configuration**, three settings that bite:

- `pool_size=5, max_overflow=5` — Supabase Free caps connections and Render's free
  container is memory-constrained; SQLAlchemy defaults are too large.
- `statement_cache_size=0` when using the Supavisor transaction pooler. Prepared
  statements do not survive a transaction pooler and the failure mode is
  intermittent `DuplicatePreparedStatementError` under concurrency, not a startup
  error.
- `pool_pre_ping=True` — after scale-to-zero or Render idle, pooled connections are
  stale and the first request after every idle window fails without it.

## Testing strategy

pgvector logic cannot be tested against SQLite; there is no shim. Rather than force
Docker into the test loop, follow the convention this repo already uses.

**Contract tests over the protocol.** One shared suite asserting behaviour — upsert
then retrieve returns the chunk, `video_id` filtering isolates videos, results order
by distance, dimension mismatch raises a clear error — parameterised over both
implementations. Chroma runs everywhere; the pgvector parameterisation is skipped
unless `TEST_DATABASE_URL` is set.

This mirrors the existing pattern exactly: the 4 local-embedding tests already skip
without extras, giving **148 passed, 4 skipped** on a bare machine and all-pass with
extras installed. CI without a database stays green.

The contract suite is also what makes `VECTOR_BACKEND` trustworthy — a flag between
two implementations is only safe if something proves they behave identically.

Additionally:

- Existing sync memory tests are rewritten as async.
- A migration test runs Alembic up on a scratch database, skipped without
  `TEST_DATABASE_URL`.
- One test asserts the degrade-don't-fail behaviour of unavailable memory.

## Definition of done

Evidence, not assertions:

- `cd backend && python -m pytest` → **148+ passed**, skip semantics unchanged.
- `cd frontend && npx tsc --noEmit && npm test` → **79 passed**.
- One manual end-to-end run: ingest a video against Postgres, ask a question,
  confirm timestamped citations resolve.

## Open decision

**Supabase pause mitigation is unresolved.** Two options were presented and the
decision was deferred:

- A scheduled GitHub Actions workflow pinging the database every few days. Free,
  but GitHub disables scheduled workflows after 60 days of repository inactivity,
  so the keep-alive decays on a similar timescale to the thing it protects, and it
  fails silently.
- Manual restore before each demo, added to `DEMO_DAY_RUNBOOK.md` alongside the
  existing Render warm-up step.

**Default if unresolved:** manual restore, documented in the runbook. It has no
silent-failure mode, and the runbook already contains a pre-demo warm-up step, so it
adds one line rather than a new mechanism. Revisit if it proves annoying in practice.

This does not block implementation — it affects operations, not code.

## Sequencing context

This design is step 3 of a four-part architecture sequence agreed during
brainstorming:

1. Resource lifecycle and boundaries (startup-scoped clients, dependency injection)
2. Pipeline consolidation (agent path, RAG path and the `tools/` wrapper overlap)
3. **State and persistence — this document**
4. Deployment topology

Step 1 is folded into this design because the `VectorStore` seam requires it. Step 2
remains separate and unstarted. Step 4 largely dissolves once the process is
stateless, since there is no longer anything stateful to split out.
