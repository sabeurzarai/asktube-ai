# Phase 3: conversation memory on Postgres — design

- **Date:** 2026-08-04
- **Branch:** `phase3/conversation-memory`
- **Status:** Approved design, not yet planned or implemented
- **Predecessors:** Phase 1 analytics (`60c353c`), Phase 2a/2b vectors (`bc93080`, `d03c758`, `e25afc9`), fixture guard (`c571e5d`)

## Problem

`ConversationMemoryService` is 31 lines holding a `dict[str, deque[ChatMessage]]` in
the API process. Every Render restart discards every conversation, and the process
cannot be scaled past one worker because a second worker would answer follow-up
questions with no history.

It is the last piece of AskTube AI's state that does not survive a restart.

## An honest note on cost and benefit

This phase is the most invasive of the four and has the smallest immediate payoff.
That was raised before the work was approved, and the decision was to proceed anyway
— completing the stateless design. Recording the reasoning so it is not rediscovered
later as a surprise:

- **Cost:** 22 call sites, many in expression positions — inside `return` statements,
  dict literals and a list comprehension — across `rag_service.py` (18) and
  `agent_service.py` (4), including a streaming generator. Phase 2b-i, by comparison,
  changed nine type annotations and no call expressions.
- **Benefit is narrower than the previous phases.** Render starts the service with
  `WEB_CONCURRENCY=1`, so multi-worker capability is theoretical on the free tier, and
  the free tier sleeps after 15 idle minutes, by which point a conversation is
  usually over. What it does buy: a restart mid-demo no longer discards the
  conversation, and the architecture stops having an exception.

Where analytics and vectors lost data irrecoverably, this loses ephemeral context.
Worth doing to finish the design, not urgent.

## Decisions taken during brainstorming

### 1. Trim on write to 8 messages per session

The in-memory store bounded itself with `deque(maxlen=8)`; Postgres bounds nothing, and
every anonymous visitor mints a session UUID whose rows would otherwise persist
forever.

After each exchange, messages older than the newest 8 for that session are deleted, in
the same transaction as the insert. This mirrors today's behaviour exactly: older
conversation is already discarded, so nothing is lost that is not already lost.

The alternatives were keeping full history (unbounded growth, orphan sessions
accumulating) or a retention job (an extra mechanism that has to run, be monitored,
and which decays silently — the same failure mode as the keep-alive workflow rejected
in Phase 1).

### 2. `create_session_id()` stays synchronous

It is `str(uuid4())` with no I/O. Making it async for symmetry would add `await` at the
two sites shaped `session_id or self.memory.create_session_id()`, where it reads
particularly badly. Only `get_messages` and `append_exchange` become async, because
only they touch the database.

### 3. Order by `id`, never by `created_at`

`now()` in Postgres returns the **transaction** timestamp. The user message and the
assistant message of one exchange are written in a single transaction and therefore
receive **identical** `created_at` values. Ordering by that column is ambiguous, and
the symptom would be a conversation history where the answer sometimes precedes the
question — intermittent, data-dependent, and painful to diagnose.

`id` is `bigserial`: monotonic within a session and unambiguous. `created_at` is kept
for human inspection only.

### 4. The metric read is passed through, not re-fetched

`rag_service.py:280` counts follow-up questions by reading the history inside metric
recording:

```python
followups = max(0, len([m for m in self.memory.get_messages(session_id) if m.role == "user"]) - 1)
```

Once `get_messages` is async and backed by Postgres, that becomes an extra round trip
on the answer path — some of which runs in background metric tasks. The caller already
holds the message list, so it is passed in rather than re-read.

## Goals

1. Conversations survive a restart.
2. The API process holds no durable state at all.
3. Public API contract, response schemas, `session_id` semantics and the frontend
   unchanged.
4. Deployment stays at **$0/month**.

## Non-goals

- Consolidating the agent and RAG answer paths.
- Retrieval quality work.
- Any frontend change.
- Cross-session or cross-user history features.

## Architecture

A package mirroring `vector_store/`, which is now the established shape in this
codebase:

```
app/services/conversation_store/
├── base.py       ConversationStore protocol
├── memory.py     in-process implementation (dev/CI)
├── postgres.py   Postgres implementation
└── factory.py    create_conversation_store + derived default
```

### The protocol

```python
class ConversationStore(Protocol):
    def create_session_id(self) -> str: ...

    async def get_messages(self, session_id: str) -> list[ChatMessage]: ...

    async def append_exchange(
        self, session_id: str, user_message: str, assistant_message: str
    ) -> None: ...
```

`max_messages` stays a constructor argument defaulting to 8, matching today.

### Backend selection

Same derived default as the vector store, for the same reason:

```
CONVERSATION_BACKEND explicit  → that backend
DATABASE_URL set               → postgres
otherwise                      → memory
```

Deriving rather than defaulting to `memory` means forgetting the variable in a
deployment with a database does not silently produce amnesia that looks like it works.

### Where the factory lives

`app/services/memory_service.py` **keeps its module path** and holds
`get_memory_service()`, exactly as `vectorstore_service.py` kept its path in Phase 2b.
Everything else in that file — `ConversationMemoryService` and its deque — moves to
`conversation_store/memory.py`.

Keeping the module means `rag_service.py` and `agent_service.py` change their import
target's *contents*, not its path, and the existing
`app.dependency_overrides[get_memory_service]` in the test suite keeps working.

Unlike the vector store there is no orchestrator: conversations need no embedding step,
so `memory_service.py` contains only the cached factory. `get_memory_service()` becomes
`@lru_cache`-wrapped for the same reason as `get_vectorstore_service()` — it is reached
through FastAPI dependencies and the Postgres implementation holds a session factory,
which must not be rebuilt per request.

## Data model

### Migration `0003` (`down_revision = "0002"`)

```sql
create table conversation_messages (
  id          bigserial primary key,
  session_id  text not null,
  role        text not null,
  content     text not null,
  created_at  timestamptz not null default now()
);

create index ix_conversation_messages_session on conversation_messages (session_id, id desc);
```

The index covers both operations: reading the newest N for a session, and finding the
rows to trim.

### Reading

```sql
select role, content
from conversation_messages
where session_id = :session_id
order by id desc
limit :limit
```

Reversed in Python so the caller receives oldest-first, matching the deque's order
today.

### Appending and trimming, one transaction

```sql
insert into conversation_messages (session_id, role, content)
values (:session_id, 'user', :user_message), (:session_id, 'assistant', :assistant_message);

delete from conversation_messages
where session_id = :session_id
  and id not in (
    select id from conversation_messages
    where session_id = :session_id
    order by id desc
    limit :max_messages
  );
```

One transaction, so a failure mid-way cannot leave a user message stored without its
answer.

## The async refactor

22 call sites. At expression positions the call is hoisted into a local:

```python
messages = await self.memory.get_messages(active_session_id)
return RAGChatResponse(..., memory=messages)
```

Hoisting is also an improvement where a method reads the history two or three times
while building one response — today that is three dict lookups, but against Postgres
it would be three round trips. Reading once and reusing is both faster and clearer.

`rag_service.py` contains a streaming generator; `await` inside an async generator is
ordinary, but the diff there needs care because the yields interleave with the reads.

## Error handling

**Conversation memory degrades, it does not fail.** If the store is unavailable, the
answer is produced with an empty history rather than refusing. Losing follow-up
context is a mild quality regression; refusing to answer is an outage.

This is a deliberate departure from retrieval, which fails loudly — retrieval *is* the
product, memory is an enhancement. It is also a new property: memory cannot fail
today, so it gets an explicit test.

Appends that fail are logged and swallowed for the same reason.

## Testing

A contract suite over both implementations, mirroring the vector store's:

- an appended exchange is readable
- messages come back oldest-first
- sessions are isolated from each other
- history is trimmed to `max_messages`, dropping the oldest
- an unknown session returns an empty list
- ordering is stable when both messages of an exchange share a timestamp

That last one is the regression test for decision 3 and cannot be written against
`created_at` alone — it is the reason `id` exists as the sort key.

The pgvector-style guard applies: the Postgres parameterisation skips without
`TEST_DATABASE_URL`, and the same destructive-fixture guard protects
`conversation_messages`.

**That guard must be shared, not copied.** It currently lives in
`tests/test_vector_store_contract.py`. Duplicating it into a second contract suite
would mean two copies that drift — and the thing that drifts would be a safeguard that
already failed once in production. It moves to `tests/conftest.py` (or a small
`tests/_scratch_db.py`), parameterised by table name, and both suites import it. The
existing four guard tests move with it.

Existing memory tests in `tests/test_memory_service.py` are rewritten against the
protocol; `test_rag_service.py` and `test_agent_service.py` need their memory fakes
made async.

## Cutover

1. Protocol, in-memory implementation, contract suite. Inert.
2. Migration `0003` and the Postgres implementation.
3. The async refactor of the 22 call sites plus the factory with the derived default.
4. Live verification: hold a conversation, restart Render, ask a follow-up that
   depends on earlier context.

Unlike Phase 2b there is no staged backend flag: the in-memory implementation is
staying permanently as the dev/CI backend, so `CONVERSATION_BACKEND=memory` is the
rollback and no code needs deleting afterwards.

## Definition of done

- `cd backend && python -m pytest` → green, skip semantics unchanged
- `cd frontend && npx tsc --noEmit && npm test` → **79 passed**
- Live: a follow-up question answered correctly **after** a Render restart, using
  context from before it
- No `self.memory.get_messages` call remains inside an expression that also builds a
  response — each is read once and reused

## Open risks

**The streaming path is the least covered.** `stream_answer` interleaves reads,
yields and appends. Its tests exercise the event sequence rather than memory
behaviour, so an ordering mistake there could pass. Worth an explicit test asserting
that a streamed exchange lands in the store exactly once.

**Two round trips become visible on the answer path.** Reading history and appending
the exchange are now network calls to Paris rather than dict operations. At Supabase
free-tier latency that is roughly 10–20 ms each, negligible against embedding and
generation — but it is no longer free, and it is on the request path.
