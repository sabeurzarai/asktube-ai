# Phase 3: Conversation Memory on Postgres Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move conversation history out of the API process into Postgres, leaving no durable state in the container.

**Architecture:** A `conversation_store/` package mirroring `vector_store/`, built alongside the existing sync `ConversationMemoryService` and inert until one task switches every caller. `memory_service.py` keeps its path and becomes the cached factory.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, pytest / pytest-asyncio in `auto` mode.

## Global Constraints

- Deployment stays at **$0/month**.
- **Tasks 1–6 change no behaviour.** The new package is built alongside the sync service; nothing calls it until Task 7.
- Baseline: **195 passed, 1 skipped**. Report actual counts; deleted tests will move it.
- Frontend untouched: `npx tsc --noEmit && npm test` → **79 passed**.
- Public API contract, response schemas and `session_id` semantics unchanged.
- **Order by `id`, never `created_at`.** `now()` is the transaction timestamp, so both messages of one exchange share it exactly. Ordering by `created_at` would intermittently place the answer before the question.
- **Trim to 8 messages per session on write**, inside the insert's transaction.
- `create_session_id()` stays **synchronous** — `uuid4()` with no I/O.
- Memory **degrades, never fails**: an unavailable store yields an empty history, not an error.
- Migration `0003` sets `down_revision = "0002"`.
- Never commit credentials. Run the suite from `backend/`, never the repo root.
- Work on branch `phase3/conversation-memory`. Do not push to `main`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/tests/conftest.py` | shared scratch-database guard, parameterised by table |
| `backend/app/services/conversation_store/base.py` | `ConversationStore` protocol |
| `backend/app/services/conversation_store/memory.py` | in-process implementation |
| `backend/app/services/conversation_store/postgres.py` | Postgres implementation |
| `backend/app/services/conversation_store/factory.py` | backend selection |
| `backend/app/services/memory_service.py` | cached factory only |
| `backend/alembic/versions/0003_conversation_messages.py` | table + index |
| `backend/tests/test_conversation_store_contract.py` | contract suite |
| `backend/app/services/rag_service.py`, `agent_service.py` | the async refactor |

---

### Task 1: Share the scratch-database guard

`reject_non_scratch_database` lives in `tests/test_vector_store_contract.py`. Phase 3 adds a second destructive fixture. Copying the guard would create two copies that drift — and the thing drifting would be a safeguard that already failed once against production.

**Files:**
- Modify: `backend/tests/conftest.py`, `backend/tests/test_vector_store_contract.py`

**Interfaces:**
- Produces: in `conftest.py`, `NotAScratchDatabase` and
  `reject_non_scratch_database(test_database_url, app_database_url, existing_row_count, table_name="transcript_chunks")`.
  Task 5 imports both.

- [ ] **Step 1: Move the guard and its tests**

Cut `NotAScratchDatabase`, `reject_non_scratch_database` and the four guard tests
(`test_guard_rejects_pointing_at_the_application_database`,
`test_guard_rejects_a_table_that_already_holds_data`,
`test_guard_allows_a_distinct_and_empty_database`,
`test_guard_allows_an_empty_database_when_the_app_has_none_configured`) from
`tests/test_vector_store_contract.py` into `tests/conftest.py`.

Add a `table_name` parameter so the message names the table actually at risk:

```python
def reject_non_scratch_database(
    test_database_url: str | None,
    app_database_url: str | None,
    existing_row_count: int,
    table_name: str = "transcript_chunks",
) -> None:
```

and use it in both messages, e.g. `f"{table_name} already holds {existing_row_count} row(s)."`

**Note:** pytest does not collect tests from `conftest.py`. Put the four guard tests in
`tests/test_scratch_db_guard.py` instead, importing from `conftest`. Moving them into
`conftest.py` would silently stop running them — a safeguard that stops being tested is
worse than one that never was.

- [ ] **Step 2: Import it in the vector contract suite**

`tests/test_vector_store_contract.py` imports the guard from `conftest` rather than
defining it. Its fixture call gains `table_name="transcript_chunks"` explicitly, so the
call site says which table it is about to empty.

- [ ] **Step 3: Verify the guard tests still run**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_scratch_db_guard.py -v
```
Expected: **4 passed**. If this collects 0 tests, they ended up somewhere pytest does not
look — fix that before continuing.

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **195 passed, 1 skipped** — unchanged, tests only moved.

- [ ] **Step 4: Commit**

```bash
git add backend/tests
git commit -m "refactor: share the scratch-database guard between contract suites"
```

---

### Task 2: Protocol and in-memory implementation

**Files:**
- Create: `backend/app/services/conversation_store/__init__.py`, `base.py`, `memory.py`
- Test: covered by Task 3's contract suite

**Interfaces:**
- Consumes: `ChatMessage` from `app.schemas.rag`.
- Produces:
  - `ConversationStore` — a `typing.Protocol` with sync `create_session_id() -> str`, and async `get_messages(session_id) -> list[ChatMessage]` and `append_exchange(session_id, user_message, assistant_message) -> None`
  - `InMemoryConversationStore(max_messages: int = 8)`

  Tasks 3–7 depend on these exact names.

- [ ] **Step 1: Create the protocol**

`backend/app/services/conversation_store/base.py`:

```python
from typing import Protocol

from app.schemas.rag import ChatMessage

DEFAULT_MAX_MESSAGES = 8


class ConversationStore(Protocol):
    """Per-session chat history.

    create_session_id is deliberately synchronous: it is uuid4() with no I/O, and
    making it async for symmetry would force `await` into the two call sites shaped
    `session_id or store.create_session_id()`.
    """

    def create_session_id(self) -> str: ...

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        """Oldest first, at most max_messages entries."""
        ...

    async def append_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Append the pair, then drop anything beyond the newest max_messages."""
        ...
```

- [ ] **Step 2: Create the in-memory implementation**

`backend/app/services/conversation_store/memory.py`, preserving today's semantics
exactly — a bounded deque per session:

```python
from collections import defaultdict, deque
from uuid import uuid4

from app.schemas.rag import ChatMessage
from app.services.conversation_store.base import DEFAULT_MAX_MESSAGES


class InMemoryConversationStore:
    """Process-local history. The development and CI backend.

    Behaviour is identical to the ConversationMemoryService it replaces, so the
    contract suite pins today's semantics before the Postgres implementation has to
    reproduce them.
    """

    def __init__(self, max_messages: int = DEFAULT_MAX_MESSAGES) -> None:
        self.max_messages = max_messages
        self._messages: dict[str, deque[ChatMessage]] = defaultdict(
            lambda: deque(maxlen=self.max_messages)
        )

    def create_session_id(self) -> str:
        return str(uuid4())

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        return list(self._messages[session_id])

    async def append_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        self._messages[session_id].append(ChatMessage(role="user", content=user_message))
        self._messages[session_id].append(
            ChatMessage(role="assistant", content=assistant_message)
        )
```

`__init__.py` exports `ConversationStore`, `DEFAULT_MAX_MESSAGES` and
`InMemoryConversationStore`.

**Do not touch `memory_service.py`.** The old sync service stays until Task 7.

- [ ] **Step 3: Verify**

```bash
cd backend && python -c "from app.services.conversation_store import InMemoryConversationStore; print('ok')"
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: prints `ok`; suite **195 passed, 1 skipped** — unchanged.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/conversation_store
git commit -m "feat: add ConversationStore protocol and in-memory implementation"
```

---

### Task 3: Contract suite

**Files:**
- Create: `backend/tests/test_conversation_store_contract.py`

**Interfaces:**
- Consumes: `InMemoryConversationStore` (Task 2).
- Produces: a `store` fixture parameterised over backends. Task 5 appends the Postgres
  parameterisation without touching a single test body.

- [ ] **Step 1: Write the suite**

```python
import pytest

from app.services.conversation_store import InMemoryConversationStore


# Task 5 appends the postgres backend here. Test bodies stay unchanged.
@pytest.fixture(params=["memory"])
async def store(request):
    if request.param == "memory":
        yield InMemoryConversationStore(max_messages=4)
        return
    raise AssertionError(f"unknown backend {request.param}")


async def test_appended_exchange_is_readable(store):
    session = store.create_session_id()
    await store.append_exchange(session, "question", "answer")

    messages = await store.get_messages(session)
    assert [(m.role, m.content) for m in messages] == [
        ("user", "question"),
        ("assistant", "answer"),
    ]


async def test_messages_come_back_oldest_first(store):
    session = store.create_session_id()
    await store.append_exchange(session, "first", "reply one")
    await store.append_exchange(session, "second", "reply two")

    contents = [m.content for m in await store.get_messages(session)]
    assert contents == ["first", "reply one", "second", "reply two"]


async def test_both_messages_of_one_exchange_keep_their_order(store):
    """Regression guard for ordering.

    In Postgres both rows of an exchange are written in one transaction and share
    an identical created_at, so any implementation ordering by that column would
    return them in an arbitrary order — putting the answer before the question.
    """
    session = store.create_session_id()
    await store.append_exchange(session, "q", "a")

    roles = [m.role for m in await store.get_messages(session)]
    assert roles == ["user", "assistant"]


async def test_sessions_are_isolated(store):
    first = store.create_session_id()
    second = store.create_session_id()
    await store.append_exchange(first, "mine", "yours")

    assert await store.get_messages(second) == []
    assert len(await store.get_messages(first)) == 2


async def test_unknown_session_returns_empty_list(store):
    assert await store.get_messages("never-seen") == []


async def test_history_is_trimmed_to_max_messages_dropping_oldest(store):
    # The fixture uses max_messages=4, so three exchanges (6 messages) must leave
    # the newest 4 and drop the first exchange entirely.
    session = store.create_session_id()
    await store.append_exchange(session, "q1", "a1")
    await store.append_exchange(session, "q2", "a2")
    await store.append_exchange(session, "q3", "a3")

    contents = [m.content for m in await store.get_messages(session)]
    assert contents == ["q2", "a2", "q3", "a3"]


async def test_create_session_id_is_unique_and_synchronous(store):
    first = store.create_session_id()
    second = store.create_session_id()
    assert first != second
    assert isinstance(first, str)
```

- [ ] **Step 2: Run**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_conversation_store_contract.py -v
```
Expected: **7 passed**, all `[memory]`.

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **202 passed, 1 skipped**.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_conversation_store_contract.py
git commit -m "test: add conversation store contract suite"
```

---

### Task 4: Migration 0003 and the Postgres implementation

**Files:**
- Create: `backend/alembic/versions/0003_conversation_messages.py`, `backend/app/services/conversation_store/postgres.py`
- Modify: `backend/app/services/conversation_store/__init__.py`

**Interfaces:**
- Produces: `PostgresConversationStore(session_factory: async_sessionmaker[AsyncSession], max_messages: int = DEFAULT_MAX_MESSAGES)`. Task 5 constructs it with `max_messages=4`.

- [ ] **Step 1: Write the migration**

```python
"""conversation messages

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Covers both operations: reading the newest N for a session, and finding the
    # rows to trim. Ordering is by id, never created_at — see the design spec.
    op.create_index(
        "ix_conversation_messages_session",
        "conversation_messages",
        ["session_id", sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_session", table_name="conversation_messages")
    op.drop_table("conversation_messages")
```

- [ ] **Step 2: Verify it compiles offline**

```bash
cd backend && DATABASE_URL='postgresql+asyncpg://u:p@localhost:5432/db' python -m alembic upgrade head --sql
```
Expected: prints `CREATE TABLE conversation_messages` and the index, exit 0. No database
is contacted in `--sql` mode.

- [ ] **Step 3: Implement the store**

`backend/app/services/conversation_store/postgres.py`:

```python
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.rag import ChatMessage
from app.services.conversation_store.base import DEFAULT_MAX_MESSAGES


class PostgresConversationStore:
    """Conversation history backed by Postgres."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        max_messages: int = DEFAULT_MAX_MESSAGES,
    ) -> None:
        self._session_factory = session_factory
        self._max_messages = max_messages

    def create_session_id(self) -> str:
        return str(uuid4())

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        # Ordered by id, not created_at: now() is the transaction timestamp, so both
        # rows of one exchange share it and ordering by it would be arbitrary.
        statement = text(
            "select role, content from conversation_messages "
            "where session_id = :session_id "
            "order by id desc limit :limit"
        )
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    statement,
                    {"session_id": session_id, "limit": self._max_messages},
                )
            ).mappings().all()

        # Newest-first from SQL so LIMIT keeps the right end; reversed here so the
        # caller receives oldest-first, matching the deque it replaces.
        return [
            ChatMessage(role=row["role"], content=row["content"])
            for row in reversed(rows)
        ]

    async def append_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        async with self._session_factory() as session:
            # One transaction: a failure must not leave a question stored without
            # its answer, nor trim against a half-written exchange.
            async with session.begin():
                await session.execute(
                    text(
                        "insert into conversation_messages (session_id, role, content) "
                        "values (:session_id, 'user', :user_message), "
                        "       (:session_id, 'assistant', :assistant_message)"
                    ),
                    {
                        "session_id": session_id,
                        "user_message": user_message,
                        "assistant_message": assistant_message,
                    },
                )
                await session.execute(
                    text(
                        "delete from conversation_messages "
                        "where session_id = :session_id and id not in ("
                        "  select id from conversation_messages "
                        "  where session_id = :session_id order by id desc limit :limit"
                        ")"
                    ),
                    {"session_id": session_id, "limit": self._max_messages},
                )
```

Export it from `__init__.py`.

- [ ] **Step 4: Verify**

```bash
cd backend && python -c "from app.services.conversation_store import PostgresConversationStore; print('ok')"
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: `ok`; **202 passed, 1 skipped** — no new tests yet.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/0003_conversation_messages.py backend/app/services/conversation_store
git commit -m "feat: add conversation_messages migration and the postgres store"
```

---

### Task 5: Run the contract suite against Postgres

**Files:**
- Modify: `backend/tests/test_conversation_store_contract.py`

**Interfaces:**
- Consumes: `PostgresConversationStore` (Task 4), the shared guard (Task 1).

- [ ] **Step 1: Extend the fixture**

Add the Postgres parameterisation, guarded exactly like the vector suite. **Test bodies
must not change** — if one needs changing, the implementations differ and that is a
finding to report, not to edit away.

```python
import os

import pytest

from app.core.config import settings
from app.services.conversation_store import (
    InMemoryConversationStore,
    PostgresConversationStore,
)
from tests.conftest import reject_non_scratch_database

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

BACKENDS = ["memory"]
if TEST_DATABASE_URL:
    BACKENDS.append("postgres")

CONTRACT_MAX_MESSAGES = 4


@pytest.fixture(params=BACKENDS)
async def store(request):
    """Yield each backend in turn.

    WARNING: the postgres branch deletes every row in conversation_messages.
    reject_non_scratch_database refuses unless the target is demonstrably disposable.
    """
    if request.param == "memory":
        yield InMemoryConversationStore(max_messages=CONTRACT_MAX_MESSAGES)
        return

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        existing = (
            await session.execute(text("select count(*) from conversation_messages"))
        ).scalar_one()
    try:
        reject_non_scratch_database(
            TEST_DATABASE_URL,
            settings.database_url,
            existing,
            table_name="conversation_messages",
        )
    except Exception:
        await engine.dispose()
        raise

    try:
        yield PostgresConversationStore(factory, max_messages=CONTRACT_MAX_MESSAGES)
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(text("delete from conversation_messages"))
        await engine.dispose()
```

Note there is **no `ALTER TABLE`** here — unlike the vector fixture, nothing about the
schema needs narrowing, so this fixture only deletes rows.

- [ ] **Step 2: Verify the skip path**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_conversation_store_contract.py -v
```
Expected: **7 passed**, all `[memory]` — no errors, no skips.

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **202 passed, 1 skipped**.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_conversation_store_contract.py
git commit -m "test: run the conversation contract against postgres when available"
```

---

### Task 6: The factory

**Files:**
- Create: `backend/app/services/conversation_store/factory.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_conversation_store_factory.py`

**Interfaces:**
- Produces: `create_conversation_store(config) -> ConversationStore`, and
  `Settings.conversation_backend` (alias `CONVERSATION_BACKEND`, default `None`).

- [ ] **Step 1: Add the setting**

In `config.py`, beside `vector_backend`:

```python
    conversation_backend: str | None = Field(
        default=None,
        alias="CONVERSATION_BACKEND",
        description=(
            "Explicit conversation store backend: 'postgres' or 'memory'. Unset "
            "derives from DATABASE_URL: set means postgres, absent means memory."
        ),
    )
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_conversation_store_factory.py`:

```python
import pytest

from app.core.config import Settings
from app.services.conversation_store import (
    InMemoryConversationStore,
    PostgresConversationStore,
)
from app.services.conversation_store.factory import create_conversation_store


def test_explicit_memory_wins_over_database_url(monkeypatch):
    monkeypatch.setenv("CONVERSATION_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    assert isinstance(create_conversation_store(Settings(_env_file=None)), InMemoryConversationStore)


def test_default_derives_postgres_when_database_url_is_set(monkeypatch):
    monkeypatch.delenv("CONVERSATION_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    assert isinstance(create_conversation_store(Settings(_env_file=None)), PostgresConversationStore)


def test_default_is_memory_without_a_database_url(monkeypatch):
    monkeypatch.delenv("CONVERSATION_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert isinstance(create_conversation_store(Settings(_env_file=None)), InMemoryConversationStore)


def test_unknown_backend_raises_naming_the_value(monkeypatch):
    monkeypatch.setenv("CONVERSATION_BACKEND", "redis")
    with pytest.raises(ValueError, match="redis"):
        create_conversation_store(Settings(_env_file=None))
```

- [ ] **Step 3: Implement**

`backend/app/services/conversation_store/factory.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.services.conversation_store.base import ConversationStore
from app.services.conversation_store.memory import InMemoryConversationStore
from app.services.conversation_store.postgres import PostgresConversationStore


def resolve_conversation_backend(config: Settings) -> str:
    """Explicit CONVERSATION_BACKEND wins; otherwise derive from DATABASE_URL.

    Deriving rather than defaulting to "memory" is deliberate: forgetting the
    variable in a deployment that has a database would otherwise start an
    in-process store that loses every conversation on restart and looks like it
    is working.
    """
    if config.conversation_backend:
        return config.conversation_backend.lower()
    return "postgres" if config.database_url else "memory"


def create_conversation_store(config: Settings) -> ConversationStore:
    backend = resolve_conversation_backend(config)

    if backend == "memory":
        return InMemoryConversationStore()

    if backend == "postgres":
        if not config.database_url:
            raise ValueError(
                "CONVERSATION_BACKEND=postgres requires DATABASE_URL to be set."
            )
        engine = create_async_engine(
            config.database_url,
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
            pool_pre_ping=True,
            # Prepared statements do not survive a transaction pooler; left enabled
            # this fails intermittently under concurrency rather than at startup.
            connect_args={"statement_cache_size": 0},
        )
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        return PostgresConversationStore(factory)

    raise ValueError(
        f"Unknown CONVERSATION_BACKEND {backend!r}. Expected 'postgres' or 'memory'."
    )
```

- [ ] **Step 4: Verify and commit**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **206 passed, 1 skipped**.

```bash
git add backend/app backend/tests/test_conversation_store_factory.py
git commit -m "feat: add conversation store factory with derived default"
```

---

### Task 7: The async refactor

The task the whole phase exists for, and the only one that changes behaviour.

**Files:**
- Modify: `backend/app/services/memory_service.py`, `backend/app/services/rag_service.py`, `backend/app/services/agent_service.py`, and the memory fakes in `backend/tests/`

**Interfaces:**
- Consumes: everything from Tasks 2–6.
- Produces: `get_memory_service() -> ConversationStore`, `@lru_cache`-wrapped.

- [ ] **Step 1: Rewrite `memory_service.py`**

It keeps its module path so imports and `app.dependency_overrides[get_memory_service]`
stay valid, but its contents reduce to the cached factory:

```python
from functools import lru_cache

from app.core.config import settings
from app.services.conversation_store import ConversationStore
from app.services.conversation_store.factory import create_conversation_store


@lru_cache
def get_memory_service() -> ConversationStore:
    """Built once per process.

    Reached through FastAPI dependencies, which run per request; the postgres
    backend holds a session factory that must not be rebuilt each time.
    """
    return create_conversation_store(settings)
```

`ConversationMemoryService` and the module-level `memory_service` singleton are
deleted — `conversation_store/memory.py` replaces the former, and callers use the
factory instead of the singleton.

- [ ] **Step 2: Refactor `rag_service.py` — 18 sites**

Change the type annotation from `ConversationMemoryService` to `ConversationStore`, and
`await` every `get_messages` / `append_exchange`.

**At expression positions, hoist into a local.** Where a method reads the history more
than once while building one response, read it **once** and reuse — three dict lookups
today become three network round trips otherwise:

```python
messages = await self.memory.get_messages(active_session_id)
return RAGChatResponse(..., memory=messages)
```

`_record_rag_metrics` currently re-reads the history to count follow-ups
(`rag_service.py:280`). **Pass the already-loaded list in as a parameter** instead of
re-reading — the caller has it, and metric recording partly runs in the background
where an extra round trip is pure cost.

`stream_answer` is an async generator: `await` inside it is ordinary, but reads,
`yield`s and the final append interleave. Work through it carefully.

- [ ] **Step 3: Refactor `agent_service.py` — 4 sites**

Same treatment. `create_session_id()` stays un-awaited.

- [ ] **Step 4: Make the test fakes async**

`tests/test_rag_service.py`, `tests/test_agent_service.py` and any other module faking
memory need `get_messages` / `append_exchange` as `async def`. `tests/test_memory_service.py`
is rewritten against the protocol, or deleted if the contract suite already covers its
assertions — say which you chose and why.

- [ ] **Step 5: Verify**

```bash
cd backend && grep -rn "ConversationMemoryService" app/ tests/
```
Expected: no output.

```bash
cd backend && grep -rn "self.memory.get_messages\|self.memory.append_exchange" app/ | grep -v await
```
Expected: no output — every call awaited.

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
cd frontend && npx tsc --noEmit && npm test
```
Expected: backend green (report the count); frontend **79 passed**.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "refactor: await conversation memory through the ConversationStore protocol"
```

---

### Task 8: Degrade rather than fail

**Files:**
- Modify: `backend/app/services/rag_service.py`, `backend/app/services/agent_service.py`
- Test: `backend/tests/test_rag_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_rag_service.py`, matching that file's existing fixtures
for building a `RAGService` — read it first and follow its patterns rather than
inventing new ones:

```python
class FailingConversationStore:
    """Every database operation fails at the connection level."""

    def create_session_id(self) -> str:
        return "session-under-test"

    async def get_messages(self, session_id):
        raise OSError("connection refused")

    async def append_exchange(self, session_id, user_message, assistant_message):
        raise OSError("connection refused")


async def test_answer_survives_a_conversation_store_that_cannot_be_read():
    # Memory is an enhancement, not the product. Losing follow-up context is a mild
    # regression; refusing to answer is an outage.
    service = make_rag_service(memory=FailingConversationStore())

    response = await service.answer(
        message="what is this about", video_id="vid1", session_id=None, top_k=3
    )

    assert response.answer
    assert response.memory == []


async def test_answer_is_returned_even_when_it_cannot_be_stored():
    # The expensive part - retrieval plus generation - already succeeded. Discarding
    # it because the history write failed would waste it for nothing.
    service = make_rag_service(memory=FailingConversationStore())

    response = await service.answer(
        message="what is this about", video_id="vid1", session_id=None, top_k=3
    )

    assert response.answer
```

`make_rag_service` stands for whatever helper that file already uses to construct the
service with fakes; if it builds one inline, follow that instead.

- [ ] **Step 2: Implement**

Wrap the memory reads and the append so a connection-level failure logs and continues.
Catch `OSError` / `ConnectionError` only — a bug must still surface.

This is deliberately the opposite of retrieval, which fails loudly: retrieval is the
product, memory is an enhancement. Losing follow-up context is a mild regression;
refusing to answer is an outage.

- [ ] **Step 3: Verify and commit**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
git add backend
git commit -m "feat: answer with an empty history when the conversation store is down"
```

---

### Task 9: Documentation

**Files:**
- Modify: `.env.example`, `CLAUDE.md` (on disk; gitignored), `AGENTS.md`

- [ ] **Step 1: `.env.example`**

Document `CONVERSATION_BACKEND` (`postgres` or `memory`; unset derives from
`DATABASE_URL`).

- [ ] **Step 2: `CLAUDE.md` / `AGENTS.md`**

Update the Configuration section and the Live deployment table: conversation history
now lives in Postgres and survives restarts; nothing durable remains in the container.
Update the test counts to whatever the suite actually reports.

- [ ] **Step 3: Verify and commit**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
git add .env.example AGENTS.md
git commit -m "docs: record that conversation history now persists"
```

---

### Task 10: Live verification (operator)

An agent cannot run this.

- [ ] **Step 1: Apply the migration**

```bash
cd backend
$env:DATABASE_URL = "<the Supabase connection string, port 5432>"
& "C:\Program Files\Python312\python.exe" -m alembic upgrade head
```
Expected: `Running upgrade 0002 -> 0003, conversation messages`.

- [ ] **Step 2: Merge, deploy, and hold a conversation**

Ask a question about an ingested video, then a **follow-up that only makes sense with
the earlier context** — for example "and what about the second point you mentioned?"

- [ ] **Step 3: The test this phase exists for**

Restart the Render service. Then ask **another context-dependent follow-up in the same
session**, without repeating the earlier questions.

If it answers coherently, the conversation survived a restart and AskTube AI holds no
durable state in the container at all.

- [ ] **Step 4: If it fails**

Set `CONVERSATION_BACKEND=memory` on Render. That restores today's behaviour without a
revert, because the in-memory implementation is staying permanently as the dev/CI
backend.

---

## What this plan deliberately does not do

- **Does not add a retention job.** Trimming on write bounds growth; a scheduled cleanup
  would be another mechanism that has to run and be monitored, and those decay silently.
- **Does not consolidate the agent and RAG answer paths.** Named a non-goal since the
  Phase 2 spec and still out of scope.
- **Does not delete the in-memory implementation.** Unlike Chroma, it is staying — it is
  the dev/CI backend and the rollback.
