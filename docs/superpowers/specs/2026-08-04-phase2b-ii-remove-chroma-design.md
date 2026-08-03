# Phase 2b-ii: remove ChromaDB — design

- **Date:** 2026-08-04
- **Branch:** `phase2b-ii/remove-chroma`
- **Status:** Approved design, not yet planned or implemented
- **Predecessor:** Phase 2b-i (`d03c758`), live-verified: transcript vectors survived a Render restart

## Why now

Phase 2b-i deliberately kept ChromaDB as the rollback. That condition has been met:
with `VECTOR_BACKEND=pgvector` set on Render, a video was ingested (10 chunks), the
service was restarted, and the same query returned the same three chunks with
identical ids and distances — read back from Postgres after the process was
destroyed. pgvector has served real production traffic. Chroma is no longer needed.

## What this phase removes and why each matters

| Removed | Reason |
|---|---|
| `ChromaVectorStoreService` | superseded by `VectorStoreService` over the `VectorStore` protocol |
| `to_chroma_metadata`, `parse_chroma_query_result`, `first_result_list`, `parse_segment_indices` | these existed only because Chroma metadata cannot hold lists, so `segment_indices` had to be JSON-encoded on write and parsed back on read. `transcript_chunks` stores a native `integer[]`. |
| `chromadb==1.3.7` | a heavy dependency; removing it shrinks the Render image and speeds builds |
| `chroma_host`, `chroma_port`, `chroma_use_http`, `chroma_persist_dir` | dead settings |
| `backend/chroma_data/` | binary vector data committed to the repository |
| `chromadb` service in `docker-compose.yml` and `docker-compose.prod.yml` | replaced by a Postgres service |
| `AnyVectorStoreService` | the union collapses to `VectorStoreService` |

### The committed binary data

`backend/chroma_data/` contains `data_level0.bin`, `header.bin` and `length.bin` —
tracked in git. `.gitignore` lists the directory, but the files were added before that
rule existed and git does not ignore already-tracked files. They are removed from the
index and from disk. Git history retains them; nothing is lost that could be needed.

## Decisions taken during brainstorming

### 1. The default becomes derived

`resolve_vector_backend(config)` changes from "always `chroma`" to:

```
VECTOR_BACKEND explicit    → that backend ('pgvector' or 'memory')
DATABASE_URL set           → pgvector
otherwise                  → memory
```

`chroma` becomes an invalid value and raises with a message saying it was removed.

This is the protection that the staged rollout deferred. Under the old fixed default,
deleting Chroma while defaulting to `memory` would mean: forget the variable on Render
and production silently runs an in-memory store that resets on every restart — and
appears to work. Deriving from `DATABASE_URL` makes production correct by default, and
a bare checkout still needs no infrastructure.

### 2. docker-compose gets a real Postgres, not nothing

`docker-compose.yml` currently runs a `chromadb` container (image
`chromadb/chroma:1.3.7`, a named volume, a `depends_on`, and `CHROMA_HOST: chromadb`
in the backend service). Removing it without replacement would leave local development
on the in-memory store — which resets between runs and behaves differently from what
production actually uses, so Postgres-specific errors would only ever appear live.

Instead a `postgres` service based on `pgvector/pgvector:pg16` takes its place, with a
named volume and a healthcheck, and the backend service gets a `DATABASE_URL` pointing
at it. Local development then runs the same engine as production, with real
persistence.

Migrations run once, manually, after first bringing the stack up
(`docker compose exec backend python -m alembic upgrade head`). An init container or
entrypoint migration step would be more automatic but adds a failure mode to the boot
path; documenting one command is the cheaper trade for a project this size.

### 3. `CHROMA_COLLECTION_NAME` stays as a fallback

A setting named after a deleted database is unattractive, but `collection_name` is a
public API field and the value is read through `resolved_collection_name`. If
`CHROMA_COLLECTION_NAME` is set in the Render environment, dropping the fallback would
silently change what the API reports. One line plus a comment explaining why it
survives is cheaper than that risk.

## Goals

1. One vector storage path in the codebase, backed by Postgres.
2. Production correct by default: `DATABASE_URL` set implies pgvector.
3. `chromadb` gone from the dependency tree and the Docker image.
4. Local development runs the same engine as production.
5. Public API contract, response schemas and the frontend unchanged.
6. Deployment stays at **$0/month**.

## Non-goals

- Conversation memory (Phase 3).
- Consolidating the agent and RAG answer paths.
- Retrieval quality work.
- Any frontend change.

## Architecture after this phase

```
app/services/
├── vectorstore_service.py     VectorStoreService only — embeddings + delegation
└── vector_store/
    ├── base.py                VectorStore protocol, cosine_distance, chunk_to_result
    ├── memory.py              in-memory implementation (dev/CI)
    ├── postgres.py            pgvector implementation
    └── factory.py             create_vector_store + resolve_vector_backend
```

`create_vector_store` builds `memory` or `pgvector` and raises for anything else,
including `chroma` — which now names a backend that no longer exists rather than one
selected at a different layer. With Chroma gone, `get_vectorstore_service()` no longer
branches: it always returns `VectorStoreService(settings, create_vector_store(settings))`,
still `@lru_cache`-wrapped because it is a FastAPI dependency and the pgvector backend
allocates a connection pool per construction.

The nine consumer sites move from `AnyVectorStoreService` to `VectorStoreService`.
Their call expressions are untouched — again only annotations.

## Text that names Chroma, and which kind it is

A survey found `chroma` in eight backend files. They are not all the same thing, and
the distinction determines what must change:

**Agent-facing tool text — must be updated.** `app/tools/ingest_video.py` and
`app/tools/store_video_vectors.py` carry `Field(description=...)` and tool
descriptions such as *"store in ChromaDB"* and *"Upsert transcript chunks into the
ChromaDB vector store"*. These are **not comments**: LangChain sends them to the
language model as part of the tool schema. Left unchanged they would describe storage
that no longer exists to the model choosing which tool to call. They also still say
"upsert", which stopped being accurate when ingestion moved to replace semantics.

**Explanatory comments — judged individually, not scrubbed.**
`vector_store/base.py` notes that `cosine_distance` matches *"pgvector's `<=>` and
Chroma's `hnsw:space: cosine`"* — that sentence explains why the value has the scale
it does, and the historical reference is still the reason. It stays. Its other
comment, *"chromadb, which is being removed"*, becomes stale and gets reworded.
`memory.py` explains that it replaces the role Chroma filled accidentally; that stays
too, since it justifies why the in-memory store exists at all.
`embedding_provider.py` warns that switching providers requires wiping the ChromaDB
collection — now the `transcript_chunks` table, so that one must be corrected or it
gives wrong operational advice.

The rule: text that a reader or a model would act on must be correct; text that
records why a decision was made may keep its historical reference.

## Testing

- The contract suite is unchanged: it already covers `memory` and `pgvector`, and the
  pgvector parameterisation still skips without `TEST_DATABASE_URL`.
- Chroma-specific tests in `tests/test_vectorstore_service.py` are deleted, not
  rewritten — the behaviour they covered no longer exists.
- Factory tests change: the case asserting an unset backend yields Chroma becomes an
  assertion that it derives from `DATABASE_URL`, and a new case asserts `chroma`
  raises.
- The two duck-typed fakes in `test_vectorstore_route.py` and `test_ingest_stream.py`
  need no change — they never depended on the concrete type.

## Verification

After merge, nothing should change: Render has both `DATABASE_URL` and
`VECTOR_BACKEND=pgvector`, so the explicit value still wins.

**The real test is removing `VECTOR_BACKEND` from Render afterwards.** If retrieval
keeps working, the derived default is doing its job — and the environment is one
variable simpler.

Rollback for this phase is not an environment variable: Chroma is gone. It is
reverting the merge. That is acceptable precisely because pgvector has already served
production traffic across a restart.

## Definition of done

- `cd backend && python -m pytest` → green, skip semantics unchanged
- `cd frontend && npx tsc --noEmit && npm test` → **79 passed**
- `grep -rn chroma backend/app --include=*.py` returns **no import, no class, no
  setting and no agent-facing description** — only the `CHROMA_COLLECTION_NAME`
  fallback and the explanatory comments listed above. A bare "no matches" is the wrong
  target: some historical references are correct and stay.
- `chromadb` absent from `requirements.txt`; `backend/chroma_data/` gone from git
- `docker compose up` starts backend, frontend and postgres, with no chromadb container
- Live: retrieval still works after the deploy, and still works after `VECTOR_BACKEND`
  is removed from Render

## Open risks

**The Render image rebuild is larger than usual.** Removing `chromadb` changes the
dependency layer, so the Docker build cache misses and the first deploy takes longer
than the recent ones. Expect a slower cold start on that deploy only.

**`docker-compose.prod.yml` is not exercised by this project's live deployment**
(Render builds from `backend/Dockerfile`). Its Chroma references are removed for
consistency, but that file's correctness cannot be verified by this work — it is not
run anywhere.
