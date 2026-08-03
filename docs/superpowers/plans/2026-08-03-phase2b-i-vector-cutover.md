# Phase 2b-i: Vector Cutover (Inert) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route ingestion and retrieval through the `VectorStore` protocol proven in Phase 2a, without changing which backend production uses.

**Architecture:** `vectorstore_service.py` keeps its module path and gains `VectorStoreService`, an orchestrator that generates embeddings and delegates persistence to an injected store. Its method signatures match today's `ChromaVectorStoreService` exactly, so the nine consumer sites change only their type annotation. The factory still defaults to Chroma, so merging this plan changes no backend.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, pgvector, ChromaDB (still present), pytest / pytest-asyncio in `auto` mode.

## Global Constraints

- Deployment stays at **$0/month**.
- **Production behaviour must not switch backends.** With no new environment variables, the app still uses ChromaDB. `VECTOR_BACKEND=pgvector` is the only way to flip it, and unsetting it rolls back.
- **One intended behaviour change ships here:** ingestion now *replaces* a video's chunks instead of upserting them, on every backend. This is the stale-chunk bug fix from the Phase 2 spec.
- **Instrumentation must survive.** `EMBEDDING_DURATION`, `VECTOR_QUERY_DURATION` and the `embedding_generated` / `vector_insert_completed` / `vector_query_completed` analytics events currently live inside `ChromaVectorStoreService`. If they are not carried into the orchestrator, the analytics dashboard silently loses data with no test failing.
- Baseline before this plan: **173 passed, 1 skipped** (contract suite's pgvector params only generate when `TEST_DATABASE_URL` is set).
- Frontend untouched: `npx tsc --noEmit && npm test` → **79 passed**.
- Public API contract and response schemas unchanged, including the `collection_name` field.
- `chromadb` stays in `requirements.txt`. Deleting it is Phase 2b-ii, after live verification.
- Never commit credentials.
- Work on branch `phase2b/vector-cutover`. Do not push to `main`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/core/config.py` | `VECTOR_BACKEND`, `VECTOR_COLLECTION_NAME` with fallback |
| `backend/app/services/vector_store/factory.py` | `create_vector_store(settings)` — staged default |
| `backend/app/services/vectorstore_service.py` | `VectorStoreService` orchestrator; embeddings + instrumentation + delegation |
| `backend/app/services/rag_service.py`, `agent_service.py`, `api/routes/vectorstore.py`, `tools/*.py` | type annotations only |
| `backend/tests/test_vector_store_factory.py` | backend selection |
| `backend/tests/test_vectorstore_service.py` | orchestrator behaviour |

---

### Task 1: `VECTOR_COLLECTION_NAME` and `VECTOR_BACKEND` settings

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.vector_backend: str | None` (alias `VECTOR_BACKEND`, default `None`), and `Settings.resolved_collection_name: str` (property). Tasks 2 and 3 depend on both.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_config.py`:

```python
# collection_name is a ChromaDB concept that leaked into the public API response
# schemas. The field stays; the setting behind it stops naming a backend that is
# being removed. CHROMA_COLLECTION_NAME remains a fallback so deployed
# environments keep working without an edit.

def test_vector_collection_name_takes_priority(monkeypatch):
    monkeypatch.setenv("VECTOR_COLLECTION_NAME", "new_name")
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "old_name")
    settings = Settings(_env_file=None)
    assert settings.resolved_collection_name == "new_name"


def test_chroma_collection_name_used_as_fallback(monkeypatch):
    monkeypatch.delenv("VECTOR_COLLECTION_NAME", raising=False)
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "old_name")
    settings = Settings(_env_file=None)
    assert settings.resolved_collection_name == "old_name"


def test_collection_name_default_when_neither_set(monkeypatch):
    monkeypatch.delenv("VECTOR_COLLECTION_NAME", raising=False)
    monkeypatch.delenv("CHROMA_COLLECTION_NAME", raising=False)
    settings = Settings(_env_file=None)
    assert settings.resolved_collection_name == "asktube_videos"


def test_vector_backend_defaults_to_none(monkeypatch):
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    settings = Settings(_env_file=None)
    assert settings.vector_backend is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_config.py -v
```
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'resolved_collection_name'`.

- [ ] **Step 3: Implement**

In `backend/app/core/config.py`, add beside the existing `chroma_collection_name` field:

```python
    vector_collection_name: str | None = Field(
        default=None,
        alias="VECTOR_COLLECTION_NAME",
        description=(
            "Logical name reported as collection_name in API responses. Replaces "
            "CHROMA_COLLECTION_NAME, which stays as a fallback."
        ),
    )
    vector_backend: str | None = Field(
        default=None,
        alias="VECTOR_BACKEND",
        description=(
            "Explicit vector store backend: 'chroma', 'pgvector' or 'memory'. "
            "Unset resolves via create_vector_store()."
        ),
    )
```

Leave `chroma_collection_name` in place — it is the fallback, and the Chroma
implementation still reads it.

Add the property next to `resolved_analytics_url`:

```python
    @property
    def resolved_collection_name(self) -> str:
        """VECTOR_COLLECTION_NAME wins; CHROMA_COLLECTION_NAME is the fallback."""
        return self.vector_collection_name or self.chroma_collection_name
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_config.py -v
```
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_config.py
git commit -m "feat: add VECTOR_COLLECTION_NAME and VECTOR_BACKEND settings"
```

---

### Task 2: The store factory

**Files:**
- Create: `backend/app/services/vector_store/factory.py`
- Modify: `backend/app/services/vector_store/__init__.py`
- Test: `backend/tests/test_vector_store_factory.py`

**Interfaces:**
- Consumes: `Settings.vector_backend` (Task 1); `InMemoryVectorStore`, `PgVectorStore` (Phase 2a).
- Produces: `create_vector_store(config: Settings) -> VectorStore`. Task 3 calls it.

**Why Chroma is still the default.** The derived default (`DATABASE_URL` set → pgvector) arrives in Phase 2b-ii, once Chroma is deleted and there is no safe fallback left. Defaulting to it now would make merging this plan switch production retrieval, with the first real request also being the first test of the wired path.

**Why `create_vector_store` never builds Chroma.** `ChromaVectorStoreService` does not
satisfy the `VectorStore` protocol: it has `upsert_chunks`/`similarity_search(query:
str)`, not the protocol's `replace_video_chunks`/`similarity_search(query_embedding:
list[float])`. So the store factory only ever builds a real `VectorStore` — `memory`
or `pgvector` — and raises for `"chroma"`, explicit or defaulted. Choosing Chroma is a
service-layer decision, made in `get_vectorstore_service()` (Task 3), which returns
`ChromaVectorStoreService` unchanged instead of asking this factory for a store.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_vector_store_factory.py`:

```python
import pytest

from app.core.config import Settings
from app.services.vector_store import InMemoryVectorStore, PgVectorStore
from app.services.vector_store.factory import create_vector_store


def test_explicit_memory_backend_wins(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    store = create_vector_store(Settings(_env_file=None))
    assert isinstance(store, InMemoryVectorStore)


def test_explicit_pgvector_backend(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    store = create_vector_store(Settings(_env_file=None))
    assert isinstance(store, PgVectorStore)


def test_chroma_backend_raises_naming_the_service_layer(monkeypatch):
    # create_vector_store() only ever builds a VectorStore. Chroma isn't one, so
    # selecting it here — explicitly or via the default — must raise rather than
    # return an object that fails the protocol on the first real call.
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")
    with pytest.raises(ValueError, match="service layer|get_vectorstore_service"):
        create_vector_store(Settings(_env_file=None))


def test_default_also_raises_since_default_resolves_to_chroma(monkeypatch):
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    with pytest.raises(ValueError, match="service layer|get_vectorstore_service"):
        create_vector_store(Settings(_env_file=None))


def test_unknown_backend_raises_naming_the_value(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "pinecone")
    with pytest.raises(ValueError, match="pinecone"):
        create_vector_store(Settings(_env_file=None))


def test_pgvector_without_database_url_raises(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ANALYTICS_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_vector_store(Settings(_env_file=None))
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_factory.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.vector_store.factory'`.

- [ ] **Step 3: Implement**

Create `backend/app/services/vector_store/factory.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.services.vector_store.base import VectorStore
from app.services.vector_store.memory import InMemoryVectorStore
from app.services.vector_store.postgres import PgVectorStore


def resolve_vector_backend(config: Settings) -> str:
    """The single place the 'chroma' default lives.

    Both the service factory (which decides between ChromaVectorStoreService and
    VectorStoreService) and this store factory (which only ever builds a
    VectorStore) resolve the backend name through this function, so they cannot
    disagree about what an unset VECTOR_BACKEND means.
    """
    return (config.vector_backend or "chroma").lower()


def create_vector_store(config: Settings) -> VectorStore:
    """Select the vector store backend.

    Only 'memory' and 'pgvector' are built here — both are real VectorStore
    implementations. 'chroma' is not: ChromaVectorStoreService does not satisfy
    the VectorStore protocol (it has upsert_chunks/similarity_search(query: str),
    not replace_video_chunks/similarity_search(query_embedding: list[float])), so
    selecting it is a service-layer decision made in
    app.services.vectorstore_service.get_vectorstore_service(), not here.
    """
    backend = resolve_vector_backend(config)

    if backend == "memory":
        return InMemoryVectorStore()

    if backend == "pgvector":
        if not config.database_url:
            raise ValueError(
                "VECTOR_BACKEND=pgvector requires DATABASE_URL to be set."
            )
        engine = create_async_engine(
            config.database_url,
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
            pool_pre_ping=True,
            connect_args={"statement_cache_size": 0},
        )
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        return PgVectorStore(factory)

    if backend == "chroma":
        raise ValueError(
            "VECTOR_BACKEND=chroma is not a VectorStore: ChromaVectorStoreService "
            "is selected in app.services.vectorstore_service.get_vectorstore_service(), "
            "not by create_vector_store()."
        )

    raise ValueError(
        f"Unknown VECTOR_BACKEND {backend!r}. Expected 'chroma', 'pgvector' or 'memory'."
    )
```

Update `backend/app/services/vector_store/__init__.py` to also export `create_vector_store`.

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vector_store_factory.py -v
```
Expected: PASS, 5 tests.

No circular import to work around: this module no longer references
`vectorstore_service` at all, lazily or otherwise.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/vector_store backend/tests/test_vector_store_factory.py
git commit -m "feat: add vector store factory defaulting to chroma"
```

---

### Task 3: The `VectorStoreService` orchestrator

The task where instrumentation is most likely to be lost. Read the existing
`ChromaVectorStoreService.upsert_chunks` and `.similarity_search` carefully first:
every Prometheus observation and analytics event in them must appear in the new class.

**Files:**
- Modify: `backend/app/services/vectorstore_service.py`
- Test: `backend/tests/test_vectorstore_service.py`

**Interfaces:**
- Consumes: `create_vector_store`, `resolve_vector_backend` (Task 2), `Settings.resolved_collection_name` (Task 1).
- Produces:
  - `VectorStoreService(config: Settings, store: VectorStore)`
  - `async upsert_chunks(chunks: list[TranscriptChunk]) -> list[str]`
  - `async similarity_search(query: str, limit: int = 5, video_id: str | None = None) -> list[VectorSearchResult]`
  - `get_vectorstore_service() -> ChromaVectorStoreService | VectorStoreService` — same name as today, so the two `app.dependency_overrides[get_vectorstore_service]` in the test suite keep working. Chosen at this layer, not inside `create_vector_store`, because Chroma is not a `VectorStore`.

  Task 4 annotates against `VectorStoreService`.

- [ ] **Step 1: Write the failing tests**

Create or extend `backend/tests/test_vectorstore_service.py`:

```python
import pytest

from app.core.config import Settings
from app.schemas.chunks import TranscriptChunk
from app.services.vector_store import InMemoryVectorStore
from app.services.vectorstore_service import VectorStoreService


def make_chunk(video_id: str, index: int, embedding=None) -> TranscriptChunk:
    return TranscriptChunk(
        chunk_id=f"{video_id}-{index}",
        index=index,
        video_id=video_id,
        text=f"chunk {index}",
        start_seconds=float(index),
        end_seconds=float(index + 1),
        segment_indices=[index],
        token_estimate=3,
        metadata={"source": "captions", "language": "en"},
        embedding=embedding,
    )


def make_service(store=None) -> VectorStoreService:
    return VectorStoreService(Settings(_env_file=None), store or InMemoryVectorStore())


async def test_upsert_with_no_chunks_is_a_noop_and_returns_empty():
    # Must NOT clear anything: no video is named, so there is nothing to replace.
    store = InMemoryVectorStore()
    await store.replace_video_chunks("vid1", [make_chunk("vid1", 0, [1.0, 0.0])])
    service = make_service(store)

    assert await service.upsert_chunks([]) == []
    assert len(await store.similarity_search([1.0, 0.0], limit=5, video_id="vid1")) == 1


async def test_upsert_rejects_chunks_spanning_multiple_videos():
    service = make_service()
    chunks = [make_chunk("vid1", 0, [1.0, 0.0]), make_chunk("vid2", 0, [1.0, 0.0])]
    with pytest.raises(ValueError, match="vid1"):
        await service.upsert_chunks(chunks)


async def test_upsert_replaces_previous_chunks_for_the_video():
    store = InMemoryVectorStore()
    service = make_service(store)
    await service.upsert_chunks([make_chunk("vid1", 0, [1.0, 0.0])])
    await service.upsert_chunks([make_chunk("vid1", 9, [1.0, 0.0])])

    results = await store.similarity_search([1.0, 0.0], limit=10, video_id="vid1")
    assert [r.chunk_id for r in results] == ["vid1-9"]


async def test_chunks_that_already_have_embeddings_are_not_re_embedded(monkeypatch):
    calls = {"count": 0}

    class FakeEmbeddings:
        async def aembed_documents(self, texts):
            calls["count"] += 1
            return [[1.0, 0.0] for _ in texts]

        async def aembed_query(self, text):
            calls["count"] += 1
            return [1.0, 0.0]

    import app.services.vectorstore_service as module

    monkeypatch.setattr(module, "create_embeddings", lambda _config: FakeEmbeddings())
    service = make_service()
    await service.upsert_chunks([make_chunk("vid1", 0, [1.0, 0.0])])
    assert calls["count"] == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vectorstore_service.py -v
```
Expected: FAIL — `ImportError: cannot import name 'VectorStoreService'`.

- [ ] **Step 3: Implement the orchestrator**

Add to `backend/app/services/vectorstore_service.py`, keeping `ChromaVectorStoreService`
and its helper functions exactly as they are — they remain the default backend until
Phase 2b-ii:

```python
class VectorStoreService:
    """Embeds chunks and queries, then delegates persistence to a VectorStore.

    Embedding generation lives here rather than in the store implementations so it
    exists once instead of per backend, and so a store can be tested without an
    OpenAI key.
    """

    def __init__(self, config: Settings, store: VectorStore) -> None:
        self.config = config
        self.store = store

    async def upsert_chunks(self, chunks: list[TranscriptChunk]) -> list[str]:
        if not chunks:
            # No video is named, so there is nothing to replace. Returning early
            # rather than clearing anything.
            return []

        video_ids = {chunk.video_id for chunk in chunks}
        if len(video_ids) > 1:
            raise ValueError(
                f"upsert_chunks expects chunks from one video, got {sorted(video_ids)}"
            )
        video_id = video_ids.pop()

        require_embedding_credentials(self.config)

        missing = [chunk for chunk in chunks if chunk.embedding is None]
        if missing:
            embedding_start = time.perf_counter()
            embeddings = create_embeddings(self.config)
            vectors = await embeddings.aembed_documents([chunk.text for chunk in missing])
            embedding_ms = (time.perf_counter() - embedding_start) * 1000
            EMBEDDING_DURATION.observe(embedding_ms / 1000)
            get_analytics_service().safe_track_background(
                get_analytics_service().track_event_safe(
                    "embedding_generated",
                    duration_ms=embedding_ms,
                    metadata_json={
                        "chunk_count": len(missing),
                        "embedding_model": self.config.embedding_model,
                    },
                )
            )
            for chunk, vector in zip(missing, vectors, strict=True):
                chunk.embedding = vector

        insert_start = time.perf_counter()
        stored_ids = await self.store.replace_video_chunks(video_id, chunks)
        insert_ms = (time.perf_counter() - insert_start) * 1000
        get_analytics_service().safe_track_background(
            get_analytics_service().track_event_safe(
                "vector_insert_completed",
                duration_ms=insert_ms,
                metadata_json={
                    "chunk_count": len(chunks),
                    "collection": self.config.resolved_collection_name,
                },
            )
        )
        return stored_ids

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        video_id: str | None = None,
    ) -> list[VectorSearchResult]:
        require_embedding_credentials(self.config)

        embeddings = create_embeddings(self.config)
        embedding_start = time.perf_counter()
        query_embedding = await embeddings.aembed_query(query)
        EMBEDDING_DURATION.observe(time.perf_counter() - embedding_start)

        query_start = time.perf_counter()
        results = await self.store.similarity_search(
            query_embedding, limit=limit, video_id=video_id
        )
        query_ms = (time.perf_counter() - query_start) * 1000
        VECTOR_QUERY_DURATION.observe(query_ms / 1000)
        get_analytics_service().safe_track_background(
            get_analytics_service().track_event_safe(
                "vector_query_completed",
                duration_ms=query_ms,
                metadata_json={
                    "video_id": video_id,
                    "limit": limit,
                    "returned_documents_count": len(results),
                },
            )
        )
        return results
```

Add the imports it needs at the top of the module: `VectorStore` from
`app.services.vector_store.base` and `create_vector_store`, `resolve_vector_backend`
from `app.services.vector_store.factory`.

Then replace the existing factory function with a single cached **service** factory,
not a cached store factory. The backend decision — Chroma or a real `VectorStore` —
has to happen at this layer, because `ChromaVectorStoreService` does not satisfy the
`VectorStore` protocol (`upsert_chunks`/`similarity_search(query: str)`, not
`replace_video_chunks`/`similarity_search(query_embedding: list[float])`). Pushing
that decision down into `create_vector_store()` was the original defect: an unset
`VECTOR_BACKEND` made `create_vector_store` return a `ChromaVectorStoreService` typed
as a `VectorStore`, and `VectorStoreService` would call `.replace_video_chunks(...)`
on it and raise `AttributeError` on the first real request — masked in tests only
because every route and tool test overrides the dependency with a fake. Deciding here
instead means the chroma branch returns `ChromaVectorStoreService` unchanged, and only
the non-chroma branches ever call `create_vector_store()`.

**The result must still be built once, not per request** — `get_vectorstore_service`
is a FastAPI `Depends`, so it runs on every request, and the pgvector branch
constructs an `AsyncEngine` with its own connection pool. Building it per request
would open a new pool per request and exhaust Supabase's connection limit within
seconds:

```python
@lru_cache
def get_vectorstore_service() -> ChromaVectorStoreService | VectorStoreService:
    """Built once per process.

    This is a FastAPI dependency and runs per request. The pgvector backend
    allocates an AsyncEngine and connection pool, so constructing it per request
    would leak pools until the database refuses connections.

    ChromaVectorStoreService is returned unchanged when the backend is chroma:
    it is not a VectorStore (no replace_video_chunks, and its similarity_search
    takes text rather than a vector), but it exposes the same public methods as
    VectorStoreService, so consumers are unaffected.
    """
    if resolve_vector_backend(settings) == "chroma":
        return ChromaVectorStoreService(settings)
    return VectorStoreService(settings, create_vector_store(settings))
```

Import `lru_cache` from `functools`. This mirrors `get_settings()` in
`app/core/config.py`, which uses the same idiom for the same reason.

There is no separate cached store factory: caching the *service* (rather than caching
a store and wrapping it fresh per call, as an earlier draft of this plan did) is what
lets the chroma branch skip `create_vector_store()` entirely while still only
allocating one pgvector engine per process.

**Add a test proving it:**

```python
def test_vector_store_is_built_once_not_per_request():
    get_vectorstore_service.cache_clear()
    first = get_vectorstore_service()
    second = get_vectorstore_service()
    # Same object: a FastAPI Depends runs per request, and the pgvector backend
    # allocates a connection pool per construction.
    assert first is second
```

**And a test proving the defect stays fixed** — that an unset `VECTOR_BACKEND`
resolves to `ChromaVectorStoreService`, not a `VectorStoreService` wrapping one:

```python
def test_get_vectorstore_service_returns_chroma_when_backend_unset(monkeypatch):
    import app.services.vectorstore_service as module

    monkeypatch.setattr(module.settings, "vector_backend", None)
    get_vectorstore_service.cache_clear()
    try:
        assert isinstance(get_vectorstore_service(), ChromaVectorStoreService)
    finally:
        get_vectorstore_service.cache_clear()
```

(`monkeypatch.setattr` on the module-level `settings` singleton, not
`monkeypatch.setenv` — `settings` is constructed once at import time via
`get_settings()`, so an env var set after that has no effect on it.)

- [ ] **Step 4: Run the tests**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vectorstore_service.py -v
```
Expected: PASS.

- [ ] **Step 5: Verify instrumentation was carried over**

```bash
cd backend && grep -c "EMBEDDING_DURATION\|VECTOR_QUERY_DURATION\|track_event_safe" app/services/vectorstore_service.py
```
Expected: at least **8** occurrences — the originals in `ChromaVectorStoreService` plus the new ones in `VectorStoreService`. A lower number means instrumentation was dropped, which no test would catch.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/vectorstore_service.py backend/tests/test_vectorstore_service.py
git commit -m "feat: add VectorStoreService orchestrator over the VectorStore protocol"
```

---

### Task 4: Switch the nine consumer annotations

Mechanical, but it is where a missed site silently keeps the old type.

**Files:**
- Modify: `backend/app/services/rag_service.py`, `backend/app/services/agent_service.py`, `backend/app/api/routes/vectorstore.py`, `backend/app/tools/__init__.py`, `backend/app/tools/retrieve_context.py`, `backend/app/tools/store_video_vectors.py`, `backend/app/tools/ingest_video.py`

**Interfaces:**
- Consumes: `VectorStoreService`, `get_vectorstore_service` (Task 3).
- Produces: nothing new.

- [ ] **Step 1: Find every site**

```bash
cd backend && grep -rn "ChromaVectorStoreService" app/
```
Record the list. Every hit **outside `app/services/vectorstore_service.py` and `app/services/vector_store/factory.py`** must change; those two legitimately still reference it.

- [ ] **Step 2: Replace the annotations**

**First add a type alias** in `app/services/vectorstore_service.py`, next to
`get_vectorstore_service`:

```python
# Either service can be returned depending on VECTOR_BACKEND. They expose the same
# public methods, so consumers are indifferent — but annotating them as one concrete
# class would misdescribe what they actually receive. Phase 2b-ii deletes
# ChromaVectorStoreService and this alias collapses to VectorStoreService.
AnyVectorStoreService = ChromaVectorStoreService | VectorStoreService
```

Then in each consumer file, change the import and every annotation from
`ChromaVectorStoreService` to `AnyVectorStoreService`. Do not change any call
expression — the method names and signatures are identical on both classes.

Annotating them as `VectorStoreService` would be wrong: `get_vectorstore_service()`
returns `ChromaVectorStoreService` whenever the backend resolves to chroma, which is
the default and therefore production's current state.

Also update the three `collection_name=settings.chroma_collection_name` sites in
`app/api/routes/vectorstore.py` to `settings.resolved_collection_name`.

- [ ] **Step 3: Verify no consumer still references the old type**

```bash
cd backend && grep -rn "ChromaVectorStoreService" app/ | grep -v "vectorstore_service.py" | grep -v "factory.py"
```
Expected: **no output**.

- [ ] **Step 4: Run the full suite**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Some tests will fail here if they fake the old interface — that is Task 5. Record which fail; do not fix them by weakening assertions.

- [ ] **Step 5: Commit**

```bash
git add backend/app
git commit -m "refactor: point consumers at VectorStoreService"
```

---

### Task 5: Update the tests that fake the store

**Files:**
- Modify: `backend/tests/test_vectorstore_route.py`, `backend/tests/test_ingest_stream.py`, and any other test Task 4 revealed as failing

**Interfaces:**
- Consumes: `VectorStoreService` (Task 3).

- [ ] **Step 1: Update the fakes**

`tests/test_vectorstore_route.py` defines `FakeVectorStoreService` and overrides
`get_vectorstore_service`. `tests/test_ingest_stream.py` overrides the same dependency.
Both must expose `upsert_chunks(chunks)` and `similarity_search(query, limit, video_id)`
with the same signatures as `VectorStoreService`.

Keep the assertions as they are. If an assertion no longer holds, that is a real
behaviour change to report — not to edit away.

- [ ] **Step 2: Run the full suite**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: all green. Count should be **173 baseline + 4 (Task 1) + 5 (Task 2) + 4 (Task 3) = 186 passed, 1 skipped**, adjusted for any test the fake updates split or merged. Report the actual number.

- [ ] **Step 3: Frontend check**

```bash
cd frontend && npx tsc --noEmit && npm test
```
Expected: **79 passed** — the API contract is unchanged, so this must not move.

- [ ] **Step 4: Commit**

```bash
git add backend/tests
git commit -m "test: update store fakes for the VectorStoreService interface"
```

---

### Task 6: Loud failures with a paused-database hint

Deferred from Phase 1 because analytics never surfaced a connection error to a user.
This is the first request path that does.

**Files:**
- Modify: `backend/app/api/routes/vectorstore.py`
- Test: `backend/tests/test_vectorstore_route.py`

**Interfaces:**
- Consumes: `VectorStoreService` (Task 3).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_vectorstore_route.py`:

```python
def test_search_returns_502_naming_a_paused_database(client, app):
    from app.api.routes.vectorstore import get_vectorstore_service

    class FailingService:
        async def similarity_search(self, query, limit=5, video_id=None):
            raise OSError("connection refused")

        async def upsert_chunks(self, chunks):
            raise OSError("connection refused")

    app.dependency_overrides[get_vectorstore_service] = lambda: FailingService()
    response = client.get("/api/vectorstore/search", params={"q": "anything"})

    assert response.status_code == 502
    detail = response.json()["detail"].lower()
    # The message must name the likely cause, not just "error" - a paused Supabase
    # project fails exactly like a network fault and costs hours otherwise.
    assert "database" in detail
    assert "paused" in detail
```

Match the existing fixtures in that file for `client` / `app`; if it builds the app
inline, follow that pattern instead.

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_vectorstore_route.py -v -k paused
```
Expected: FAIL — either a 500 or a detail without those words.

- [ ] **Step 3: Implement**

In `app/api/routes/vectorstore.py`, wrap the store calls in the search and ingest
handlers so a connection-level failure becomes:

```python
    except (OSError, ConnectionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Vector store unavailable. If DATABASE_URL points at Supabase, the "
                "project may be paused — Free plan projects pause after 7 days of "
                "low activity and must be restored from the dashboard."
            ),
        ) from exc
```

Follow the existing 502 style already used in this module. Do not catch broad
`Exception` — a bug should still surface as a 500.

**Also handle the dimension mismatch**, which the design requires and which is a
different failure with a different fix. `PgVectorStore.replace_video_chunks` and
`cosine_distance` both raise `ValueError` naming the offending sizes when an
embedding's length does not match the column. Left uncaught it is a 500 that reads
like a crash, when in fact it means the embedding provider was switched without
wiping and re-ingesting. Add to the ingest handler:

```python
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Vector store rejected the chunks: {exc}. Switching EMBEDDING_PROVIDER "
                "changes the vector dimension and requires wiping and re-ingesting."
            ),
        ) from exc
```

Order matters: catch `ValueError` before the broader connection clause, and note that
`upsert_chunks` also raises `ValueError` for chunks spanning multiple videos — that
message is equally useful to a caller, so one handler covers both.

Add a second test asserting a dimension-mismatch `ValueError` becomes a 502 whose
detail names re-ingesting.

- [ ] **Step 4: Run the suite**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: all green, one more test than Task 5.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/vectorstore.py backend/tests/test_vectorstore_route.py
git commit -m "feat: surface vector store outages as 502 with a paused-database hint"
```

---

### Task 7: Documentation

**Files:**
- Modify: `.env.example`, `CLAUDE.md` (on disk; untracked), `AGENTS.md`

- [ ] **Step 1: `.env.example`**

```bash
# ── Vector store ──────────────────────────────────────────────────────────
# Backend selection. Unset = chroma (current behaviour) while ChromaDB exists.
# Set to pgvector to use the Postgres store; unset it again to roll back.
# VECTOR_BACKEND=pgvector
# Logical name reported as collection_name in API responses.
# Falls back to CHROMA_COLLECTION_NAME when unset.
VECTOR_COLLECTION_NAME=asktube_videos
```

- [ ] **Step 2: `CLAUDE.md` and `AGENTS.md`**

Add to the Configuration section of both (they are kept in sync):

```markdown
- Vector store switch: `VECTOR_BACKEND=chroma|pgvector|memory` — factory in
  `backend/app/services/vector_store/factory.py`. Unset defaults to `chroma` while
  ChromaDB still exists; Phase 2b-ii changes that to derive from `DATABASE_URL`.
  `VectorStoreService` in `vectorstore_service.py` owns embedding generation and
  delegates persistence to the selected store. Re-ingesting a video now REPLACES its
  chunks rather than upserting, so a chunking-parameter change no longer leaves stale
  chunks behind.
```

- [ ] **Step 3: Verify and commit**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: unchanged from Task 6.

```bash
git add .env.example AGENTS.md
git commit -m "docs: document VECTOR_BACKEND and the replace-on-ingest change"
```

`CLAUDE.md` is gitignored — edit it on disk, but it will not appear in the commit.

---

### Task 8: Live verification (operator, requires credentials)

An agent cannot run this. It is the gate before Phase 2b-ii deletes Chroma.

- [ ] **Step 1: Confirm production is unchanged after deploy**

Merge and deploy, then check `/health` returns 200 and a chat query still works.
`VECTOR_BACKEND` is unset, so Chroma is still in use — nothing should differ.

- [ ] **Step 2: Flip to pgvector**

On Render, add `VECTOR_BACKEND=pgvector`. Wait for the redeploy.

- [ ] **Step 3: Exercise the real path**

Ingest a video through the UI, ask a question about it, and confirm the timestamped
citations resolve to the right moments.

- [ ] **Step 4: The check this entire project exists for**

Restart the Render service manually. Then ask a question about the **same video
without re-ingesting it**.

If it answers with citations, transcript vectors have survived a restart for the first
time, and `DEMO_DAY_RUNBOOK.md` step 0 no longer needs the re-ingest instruction.

- [ ] **Step 5: If anything fails**

Unset `VECTOR_BACKEND` on Render. Production returns to Chroma on the next deploy.
Report the failure before proceeding to Phase 2b-ii.

---

## What this plan deliberately does not do

- **Does not delete ChromaDB.** `ChromaVectorStoreService` and `chromadb==1.3.7` stay.
  Until pgvector has served production traffic, Chroma is the rollback.
- **Does not change the default backend.** That is Phase 2b-ii, together with the
  deletion, once Task 8 has passed.
- **Does not touch the frontend.** The `collection_name` field keeps its shape and its
  value; only the setting behind it is renamed.
