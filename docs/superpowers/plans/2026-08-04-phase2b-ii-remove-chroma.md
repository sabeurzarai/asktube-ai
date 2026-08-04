# Phase 2b-ii: Remove ChromaDB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete ChromaDB and make Postgres the default, leaving one vector storage path.

**Architecture:** `resolve_vector_backend` stops returning `chroma` and derives from `DATABASE_URL` instead. `ChromaVectorStoreService` and its Chroma-only helpers are deleted, `get_vectorstore_service()` stops branching, and the `AnyVectorStoreService` union collapses to `VectorStoreService`. docker-compose swaps its `chromadb` container for `pgvector/pgvector:pg16`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, pgvector, Alembic, Docker Compose, pytest / pytest-asyncio in `auto` mode.

## Global Constraints

- Deployment stays at **$0/month**.
- **Production must keep working across the merge.** Render has both `DATABASE_URL` and `VECTOR_BACKEND=pgvector` set, so the explicit value still wins and behaviour is unchanged. Removing `VECTOR_BACKEND` afterwards is the test of the new default.
- **Rollback for this phase is reverting the merge, not an env var.** Chroma is gone. That is acceptable only because pgvector already served production traffic across a restart (verified: same chunk ids, same distances, after a Render restart).
- Baseline: **192 passed, 1 skipped**. Deleting Chroma tests will lower the count — report the actual number rather than forcing a target.
- Frontend untouched: `npx tsc --noEmit && npm test` → **79 passed**.
- Public API contract and response schemas unchanged, including `collection_name`.
- `CHROMA_COLLECTION_NAME` **stays** as the fallback behind `VECTOR_COLLECTION_NAME`. Dropping it would silently change what the API reports if it is set in Render's environment.
- Never commit credentials.
- Work on branch `phase2b-ii/remove-chroma`. Do not push to `main`.

## File Structure

| File | Change |
|---|---|
| `backend/app/services/vector_store/factory.py` | derived default; `chroma` raises |
| `backend/app/services/vectorstore_service.py` | delete Chroma class + helpers; stop branching; collapse alias |
| `backend/app/services/rag_service.py`, `api/routes/vectorstore.py`, `tools/*.py` | annotations `AnyVectorStoreService` → `VectorStoreService` |
| `backend/app/core/config.py` | delete four dead `CHROMA_*` settings |
| `backend/requirements.txt` | delete `chromadb==1.3.7` |
| `backend/chroma_data/` | delete from git and disk |
| `backend/app/tools/ingest_video.py`, `store_video_vectors.py` | agent-facing descriptions |
| `docker-compose.yml`, `docker-compose.prod.yml` | swap chromadb for postgres |
| `.env.example`, `CLAUDE.md`, `AGENTS.md` | docs |

---

### Task 1: Derive the default backend

**Files:**
- Modify: `backend/app/services/vector_store/factory.py`
- Test: `backend/tests/test_vector_store_factory.py`

**Interfaces:**
- Produces: `resolve_vector_backend(config) -> str` returning `"pgvector"` or `"memory"`, never `"chroma"`. Task 2 relies on it never returning `"chroma"`.

**Why this is the protection the staged rollout deferred.** With Chroma deleted, a fixed `memory` default would mean: forget `VECTOR_BACKEND` on Render and production silently runs an in-memory store that resets every restart *and appears to work*. Deriving from `DATABASE_URL` makes production correct by default while a bare checkout still needs no infrastructure.

- [ ] **Step 1: Update the tests**

In `backend/tests/test_vector_store_factory.py`, replace `test_default_is_chroma_while_chroma_exists` with:

```python
def test_default_derives_pgvector_when_database_url_is_set(monkeypatch):
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    store = create_vector_store(Settings(_env_file=None))
    assert isinstance(store, PgVectorStore)


def test_default_is_memory_without_a_database_url(monkeypatch):
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = create_vector_store(Settings(_env_file=None))
    assert isinstance(store, InMemoryVectorStore)


def test_chroma_is_no_longer_a_valid_backend(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")
    with pytest.raises(ValueError, match="removed"):
        create_vector_store(Settings(_env_file=None))
```

Remove the `ChromaVectorStoreService` import from this file. Keep the existing explicit-backend and missing-`DATABASE_URL` tests unchanged.

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_factory.py -v
```
Expected: FAIL — the default still resolves to `chroma`.

- [ ] **Step 3: Implement**

In `factory.py`, replace `resolve_vector_backend` and the `chroma` branch:

```python
def resolve_vector_backend(config: Settings) -> str:
    """Explicit VECTOR_BACKEND wins; otherwise derive from DATABASE_URL.

    Deriving rather than defaulting to "memory" is deliberate: forgetting the
    variable in a deployment that has a database would otherwise start an
    in-memory store that resets on every restart and looks like it is working.
    A bare checkout has no DATABASE_URL and still needs no infrastructure.
    """
    if config.vector_backend:
        return config.vector_backend.lower()
    return "pgvector" if config.database_url else "memory"
```

And in `create_vector_store`, replace the `chroma` branch with an explicit rejection:

```python
    if backend == "chroma":
        raise ValueError(
            "VECTOR_BACKEND=chroma is no longer supported: ChromaDB was removed in "
            "favour of Postgres + pgvector. Unset VECTOR_BACKEND to derive the "
            "backend from DATABASE_URL."
        )
```

Keep it as a named case rather than letting it fall into the generic unknown-backend
error: an operator with `chroma` still set in an old environment deserves to be told
what happened, not just that the value is unrecognised.

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_factory.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/vector_store/factory.py backend/tests/test_vector_store_factory.py
git commit -m "feat: derive the vector backend from DATABASE_URL"
```

---

### Task 2: Delete `ChromaVectorStoreService`

**Files:**
- Modify: `backend/app/services/vectorstore_service.py`
- Modify: `backend/tests/test_vectorstore_service.py`

**Interfaces:**
- Consumes: `resolve_vector_backend` never returning `"chroma"` (Task 1).
- Produces: `get_vectorstore_service() -> VectorStoreService` — no longer a union. Task 3 annotates against it.

- [ ] **Step 1: Delete the Chroma tests first**

In `backend/tests/test_vectorstore_service.py`, delete every test exercising
`ChromaVectorStoreService`, and the import. Keep every `VectorStoreService` test and
the caching-identity test.

Deleting rather than rewriting is correct: they covered behaviour that no longer
exists. Their replacement already exists — the contract suite proves the surviving
backends behave identically.

- [ ] **Step 2: Delete the class and its helpers**

From `backend/app/services/vectorstore_service.py` remove:

- `class ChromaVectorStoreService` in full
- `to_chroma_metadata`
- `parse_chroma_query_result`
- `first_result_list`
- `parse_segment_indices`
- the `chromadb` and `Collection` imports

The last four exist only because Chroma metadata cannot hold lists, so
`segment_indices` had to be JSON-encoded on write and parsed back on read.
`transcript_chunks` stores a native `integer[]`.

Then simplify the factory and collapse the alias:

```python
@lru_cache
def get_vectorstore_service() -> VectorStoreService:
    """Built once per process.

    This is a FastAPI dependency and runs per request; the pgvector backend
    allocates a connection pool per construction.
    """
    return VectorStoreService(settings, create_vector_store(settings))
```

**Keep the `AnyVectorStoreService` name alive for one task**, now pointing at a single
class:

```python
# Transitional: consumers still import this name. Task 3 replaces their annotations
# and deletes this line. Keeping it for one task means the tree never sits broken.
AnyVectorStoreService = VectorStoreService
```

Deleting the alias here instead would leave every consumer's import broken until
Task 3 lands. A plan should not specify a state it knows is broken — a reviewer or a
resumed session would be unable to tell a deliberate breakage from a real one.

- [ ] **Step 3: Verify nothing in the app still imports Chroma**

```bash
cd backend && grep -rn "chromadb\|ChromaVectorStoreService" app/ --include=*.py
```
Expected: no output.

- [ ] **Step 4: Run the suite**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **green**. The count drops below 192 because you deleted the Chroma tests —
report the actual number. If anything fails, it is a real problem, not an expected
intermediate state.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/vectorstore_service.py backend/tests/test_vectorstore_service.py
git commit -m "refactor: delete ChromaVectorStoreService and its metadata helpers"
```

---

### Task 3: Collapse the annotations

**Files:**
- Modify: `backend/app/services/rag_service.py`, `backend/app/api/routes/vectorstore.py`, `backend/app/tools/ingest_video.py`, `backend/app/tools/retrieve_context.py`, `backend/app/tools/store_video_vectors.py`

- [ ] **Step 1: Find every site**

```bash
cd backend && grep -rn "AnyVectorStoreService" app/
```

- [ ] **Step 2: Replace, then delete the transitional alias**

Change every import and annotation from `AnyVectorStoreService` to
`VectorStoreService`. Do not change call expressions.

Then delete the transitional line Task 2 left in
`backend/app/services/vectorstore_service.py`:

```python
AnyVectorStoreService = VectorStoreService
```

It existed only so Task 2 could land without breaking consumer imports.

- [ ] **Step 3: Verify**

```bash
cd backend && grep -rn "AnyVectorStoreService" app/
```
Expected: no output.

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: green. Count will be below 192 because Task 2 deleted tests — report the
actual number.

```bash
cd frontend && npx tsc --noEmit && npm test
```
Expected: **79 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/app
git commit -m "refactor: collapse AnyVectorStoreService to VectorStoreService"
```

---

### Task 4: Remove the dependency, the settings, and the committed data

**Files:**
- Modify: `backend/requirements.txt`, `backend/app/core/config.py`
- Delete: `backend/chroma_data/`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Remove the dependency**

Delete `chromadb==1.3.7` from `backend/requirements.txt`.

- [ ] **Step 2: Remove the dead settings**

From `backend/app/core/config.py` delete `chroma_host`, `chroma_port`,
`chroma_use_http` and `chroma_persist_dir`.

**Keep `chroma_collection_name`.** It is the fallback behind
`VECTOR_COLLECTION_NAME`, and `resolved_collection_name` reads it. Add a comment
saying it survives only as a compatibility alias for deployments that still set it.

Check `tests/test_config.py` for assertions on the deleted settings and remove those
tests; keep the `resolved_collection_name` fallback tests, which must still pass.

- [ ] **Step 3: Remove the committed binary data**

```bash
cd backend && git rm -r --cached chroma_data && rm -rf chroma_data
```

`.gitignore` already lists `backend/chroma_data/`; the files were tracked from before
that rule, and git does not ignore already-tracked files. Git history retains them.

- [ ] **Step 4: Verify**

```bash
cd backend && git status --short | head
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: `chroma_data` shown as deleted; suite green.

Confirm the app still imports with the settings gone:
```bash
cd backend && OPENAI_API_KEY=dummy python -c "from app.main import app; print('imports ok')"
```

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/app/core/config.py backend/tests/test_config.py
git commit -m "chore: drop the chromadb dependency, dead settings and committed vector data"
```

Do NOT `git add backend/chroma_data` — the directory no longer exists on disk, so the
command fails. `git rm -r --cached` in Step 3 already staged the deletion; it is
included in this commit without being named.

---

### Task 5: Correct the agent-facing text

These are **not comments**. LangChain sends `Field(description=...)` and tool
descriptions to the language model as part of the tool schema, so leaving them would
describe storage that no longer exists to the model choosing which tool to call.

**Files:**
- Modify: `backend/app/tools/ingest_video.py`, `backend/app/tools/store_video_vectors.py`, `backend/app/services/embedding_provider.py`, `backend/app/services/vector_store/base.py`

- [ ] **Step 1: Fix the tool descriptions**

In `app/tools/ingest_video.py`, replace "ChromaDB" with "the vector store" in both the
`Field(description=...)` and the tool description.

In `app/tools/store_video_vectors.py`, do the same — and note the description also
says "upsert", which stopped being accurate when ingestion moved to replace semantics.
Reword it to say the chunks **replace** any previously stored chunks for that video,
so the model is told what actually happens.

- [ ] **Step 2: Fix the operational advice**

`app/services/embedding_provider.py` says switching providers requires wiping "any
ChromaDB collection". That is now the `transcript_chunks` table. Correct it, or the
comment gives wrong instructions to whoever switches providers.

- [ ] **Step 3: Reword only the stale comment in `base.py`**

`vector_store/base.py` has two Chroma references:

- *"Matches pgvector's `<=>` operator and Chroma's `hnsw:space: cosine`"* — **keep it.** It explains why the distance has the scale it does, and the historical reference is the reason.
- *"chromadb, which is being removed"* — reword to past tense; it is removed.

Do not scrub `memory.py`'s comment about replacing the role Chroma filled — it
justifies why the in-memory store exists.

- [ ] **Step 4: Verify**

```bash
cd backend && grep -rn "hroma" app/ --include=*.py
```
Expected: only `chroma_collection_name` in `config.py`, and the two kept explanatory
comments. No imports, no class, no agent-facing description.

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: unchanged from Task 4.

- [ ] **Step 5: Commit**

```bash
git add backend/app
git commit -m "docs: stop telling the agent it is writing to ChromaDB"
```

---

### Task 6: Swap the compose container

**Files:**
- Modify: `docker-compose.yml`, `docker-compose.prod.yml`

- [ ] **Step 1: Replace the service in `docker-compose.yml`**

Remove the `chromadb` service, its `chroma_data` volume, the backend's `depends_on:
chromadb`, and the `CHROMA_HOST` / `CHROMA_PORT` / `CHROMA_USE_HTTP` environment keys.

Add, following the file's existing style and indentation:

```yaml
  postgres:
    container_name: asktube-postgres
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: asktube
      POSTGRES_PASSWORD: asktube
      POSTGRES_DB: asktube
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U asktube"]
      interval: 5s
      timeout: 5s
      retries: 10
```

Add `postgres_data:` under `volumes:` where `chroma_data:` was.

In the backend service, add:

```yaml
      DATABASE_URL: postgresql+asyncpg://asktube:asktube@postgres:5432/asktube
```

and make it depend on postgres being healthy:

```yaml
    depends_on:
      postgres:
        condition: service_healthy
```

These credentials are local-only container defaults, not secrets — they never leave
the compose network.

- [ ] **Step 2: Clean `docker-compose.prod.yml`**

Remove its Chroma references the same way. **Note this file is not exercised by the
live deployment** — Render builds from `backend/Dockerfile` — so this change is for
consistency and cannot be verified by running it. Say so in your report.

- [ ] **Step 3: Verify the compose file parses**

```bash
docker compose config >/dev/null && echo "compose config valid"
```
If Docker is unavailable in your environment, say so and skip — do not guess.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml docker-compose.prod.yml
git commit -m "chore: replace the chromadb container with postgres+pgvector"
```

---

### Task 7: Documentation

**Files:**
- Modify: `.env.example`, `CLAUDE.md` (on disk; gitignored), `AGENTS.md`, `DEMO_DAY_RUNBOOK.md`

- [ ] **Step 1: `.env.example`**

Remove `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_USE_HTTP`, `CHROMA_PERSIST_DIR`. Keep
`CHROMA_COLLECTION_NAME` with a note that it is a compatibility fallback. Update the
`VECTOR_BACKEND` comment: values are now `pgvector` or `memory`, and unset derives
from `DATABASE_URL`.

- [ ] **Step 2: `CLAUDE.md` and `AGENTS.md`**

They are kept in sync; apply the same content to both. `CLAUDE.md` is gitignored —
edit it on disk, it will not appear in the commit.

Update the vector store section to state: ChromaDB is removed; `VECTOR_BACKEND` is
`pgvector` or `memory` and unset derives from `DATABASE_URL`; re-ingest replaces a
video's chunks (now unconditionally true, since the Chroma path is gone).

Also update the "Live deployment" table row for the vector store — it currently says
ChromaDB embedded in the backend process.

- [ ] **Step 3: `DEMO_DAY_RUNBOOK.md`**

Step 0 instructs re-ingesting a demo video before presenting, because the vector store
reset on restart. That is no longer true. Replace it with a note that transcript
vectors persist in Postgres, and that what still needs warming is the Render service
itself (free tier sleeps after 15 idle minutes).

This is the operator-visible payoff of the whole project — make sure the runbook
actually says so rather than leaving a stale instruction.

- [ ] **Step 4: Verify and commit**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: unchanged.

```bash
git add .env.example AGENTS.md DEMO_DAY_RUNBOOK.md
git commit -m "docs: record that ChromaDB is gone and vectors now persist"
```

---

### Task 8: Live verification (operator, requires deploy access)

An agent cannot run this.

- [ ] **Step 1: Merge and deploy**

Nothing should change: Render has `VECTOR_BACKEND=pgvector` explicitly set, so it wins
over the new derived default.

Expect a **slower build than usual** — removing `chromadb` invalidates the dependency
layer, so the Docker cache misses.

- [ ] **Step 2: Confirm retrieval still works**

```bash
curl -s "https://asktube-ai-q2gi.onrender.com/api/vectorstore/search?q=what%20is%20this%20about&limit=3"
```
Expected: the previously ingested chunks, unchanged.

- [ ] **Step 3: The actual test of this phase — remove `VECTOR_BACKEND`**

Delete `VECTOR_BACKEND` from Render's environment. After the redeploy, run the same
query.

If it still returns chunks, the derived default works and production is one variable
simpler. If it returns empty, the derivation is wrong and the app silently fell back
to an in-memory store — which is exactly the failure the derived default exists to
prevent, so investigate rather than shrugging.

- [ ] **Step 4: If anything fails**

Rollback is reverting the merge — Chroma is gone, so there is no env-var escape. That
is acceptable because pgvector already served production traffic across a restart, but
it means a failure here needs a revert rather than a toggle.

---

## What this plan deliberately does not do

- **Does not touch conversation memory.** That is Phase 3, and it is the last piece of
  AskTube AI's state that still dies on restart.
- **Does not consolidate the agent and RAG answer paths.** Named as a non-goal in the
  Phase 2 spec and still out of scope.
- **Does not tune HNSW or retrieval quality.** The index keeps pgvector defaults,
  which are comfortable at this data size.
