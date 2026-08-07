# Contextualized Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make follow-up questions retrieve what the user actually means, and prove it with a before/after measurement.

**Architecture:** A rewrite step in `rag_service.prepare_context` turns a follow-up into a standalone search query using the conversation history, but only when history exists. Generation still receives the original question. A separate retrieval-level evaluation records a baseline first.

**Tech Stack:** FastAPI, LangChain, pgvector, pytest / pytest-asyncio in `auto` mode.

## Global Constraints

- Deployment stays at **$0/month**.
- **Only the retrieval query is rewritten.** The generation prompt keeps receiving the original user message — otherwise the system answers a question nobody asked.
- **No rewrite without history.** First turns must cost nothing extra and must not be degraded.
- **Rewrite failure falls back to the raw message.** An enhancement must never prevent an answer.
- Baseline: **201 passed, 1 skipped**. Report actual counts.
- Frontend untouched: `npx tsc --noEmit && npm test` → **79 passed**.
- Public API contract and response schemas unchanged.
- Run the suite from `backend/`, never the repo root.
- Never commit credentials.
- Work on branch `quality/contextualized-retrieval`. Do not push to `main`.

## Ground truth: the chunks of `fWjsdhR3z3c`

Read from the live API (`GET /api/videos/fWjsdhR3z3c/chunks`) so the fixture's
expectations are derived, not invented. The video has 10 chunks:

| # | Range | Distinctive content |
|---|---|---|
| 0 | 0–74s | "python 3.8 … along with **pycharm** as my code editor" |
| 3 | 204–285s | "to do addition you just need to add a **plus symbol**" |
| 5 | 355–429s | "next we have a **while loop** … i equals zero" |
| 6 | 425–494s | "it will reach this **break sta**tement" |
| 7 | 491–564s | "functions … such as get internet and **run game**" |

**The observed failure explained:** the follow-up *"And what did you just say it uses?"*
should reach chunk 0 (pycharm, python 3.8). It returned chunk 7 (functions).

## File Structure

| File | Responsibility |
|---|---|
| `backend/tests/fixtures/retrieval_eval_cases.json` | conversation cases with expected substrings |
| `backend/scripts/run_retrieval_eval.py` | operator-run measurement |
| `backend/app/services/rag_service.py` | the rewrite step |
| `backend/tests/test_rag_service.py` | rewrite behaviour |

---

### Task 1: The evaluation case set

**Files:**
- Create: `backend/tests/fixtures/retrieval_eval_cases.json`

**Interfaces:**
- Produces: the fixture consumed by Task 2's runner. Its schema is `{"video_id", "cases": [{"name", "history", "question", "expect_chunk_containing"}]}`.

- [ ] **Step 1: Write the fixture**

Substrings below are taken from the actual chunks listed above — do not change them
without re-reading the chunks, and do not add a case whose expectation you have not
verified appears in exactly one chunk.

```json
{
  "video_id": "fWjsdhR3z3c",
  "cases": [
    {
      "name": "first turn, specific question about arithmetic",
      "history": [],
      "question": "How do I do addition in Python?",
      "expect_chunk_containing": "plus symbol"
    },
    {
      "name": "first turn, specific question about loops",
      "history": [],
      "question": "How does a while loop work?",
      "expect_chunk_containing": "while loop"
    },
    {
      "name": "follow-up referring to the previous answer",
      "history": [
        {"role": "user", "content": "What is this video about?"},
        {"role": "assistant", "content": "This video is about getting started with Python in less than 10 minutes."}
      ],
      "question": "And what did you just say it uses?",
      "expect_chunk_containing": "pycharm"
    },
    {
      "name": "follow-up asking for an example of the previous topic",
      "history": [
        {"role": "user", "content": "What does the pass keyword do?"},
        {"role": "assistant", "content": "pass lets you define a function without writing its logic yet."}
      ],
      "question": "give me an example of one",
      "expect_chunk_containing": "run game"
    },
    {
      "name": "vague follow-up (hallucination risk case)",
      "history": [
        {"role": "user", "content": "How does a while loop work?"},
        {"role": "assistant", "content": "It increments i by one until i reaches five."}
      ],
      "question": "and the next one?",
      "expect_chunk_containing": "break sta"
    }
  ]
}
```

The first two cases are the **regression guards**: they have no history, so the rewrite
must leave them untouched. If they stop hitting after the change, the rewrite is
damaging queries it was never meant to touch.

The last case is the **hallucination guard** named in the design's open risks. *"and the
next one?"* gives a model room to invent a topic. It may legitimately miss — what
matters is seeing whether the rewrite invents something confidently wrong.

- [ ] **Step 2: Verify the substrings really are unique**

```bash
curl -s "https://asktube-ai-q2gi.onrender.com/api/videos/fWjsdhR3z3c/chunks" > /tmp/chunks.json
```

For each of `plus symbol`, `while loop`, `pycharm`, `run game`, `break sta`, confirm it
appears in **exactly one** chunk. A substring appearing in two chunks makes its case
pass for the wrong reason.

Report which chunk index each substring matched.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/fixtures/retrieval_eval_cases.json
git commit -m "test: add retrieval evaluation cases derived from real chunks"
```

---

### Task 2: The measurement runner

**Files:**
- Create: `backend/scripts/run_retrieval_eval.py`

**Interfaces:**
- Consumes: the fixture from Task 1.
- Produces: a script printing per-case hit / rank / best distance, and a hit-rate total.

- [ ] **Step 1: Write the runner**

It must:

- load the fixture
- for each case, build a `RAGService` whose conversation store is **pre-loaded with that
  case's history** — use `InMemoryConversationStore` and `append_exchange` to seed it, so
  no LLM call is needed to produce the assistant side
- call `prepare_context(message=case["question"], video_id=..., session_id=<seeded>, top_k=5)`
- check whether any returned chunk's `text` contains `expect_chunk_containing`
- print: case name, HIT/MISS, rank of the matching chunk (1-based, `-` on miss), best distance
- print a final hit rate, e.g. `3/5`

Follow the existing `scripts/run_evaluation.py` for structure, argument handling and
output style — read it first.

It needs `DATABASE_URL` and `OPENAI_API_KEY`, so it is operator-run and not part of the
test suite. Say so in its docstring, along with the prerequisite that `fWjsdhR3z3c` must
already be ingested.

- [ ] **Step 2: Verify it runs without a database**

```bash
cd backend && python -c "import ast; ast.parse(open('scripts/run_retrieval_eval.py').read()); print('parses')"
```
Expected: `parses`. Actually executing it needs credentials — that is Task 3.

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **201 passed, 1 skipped** — unchanged; you added no tests.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/run_retrieval_eval.py
git commit -m "feat: add a retrieval-level evaluation runner"
```

---

### Task 3: Record the baseline (operator)

An agent cannot run this — it needs the database and an OpenAI key.

- [ ] **Step 1: Run it against the current code**

```bash
cd backend
$env:DATABASE_URL = "<the Supabase connection string, port 5432>"
& "C:\Program Files\Python312\python.exe" scripts/run_retrieval_eval.py
```

- [ ] **Step 2: Record the output verbatim**

Paste the table into `.superpowers/sdd/progress.md` under a `BASELINE` heading. This is
the number the change has to beat, and it is worthless if reconstructed from memory
later.

**Expected shape of the result:** the two first-turn cases should HIT. At least the
"what did you just say it uses" case should MISS — that is the failure being fixed. If
everything already hits, stop and report: either the cases are too easy or the problem is
not what the design assumes.

---

### Task 4: The rewrite step

**Files:**
- Modify: `backend/app/services/rag_service.py`
- Test: `backend/tests/test_rag_service.py`

**Interfaces:**
- Produces: `RAGService._contextualize(message: str, history: list[ChatMessage]) -> str`.

- [ ] **Step 1: Write the failing tests**

Follow the existing patterns in `test_rag_service.py` for constructing a service — read
it first rather than inventing fixtures.

```python
async def test_contextualize_returns_the_message_unchanged_without_history():
    # First turns must cost nothing and must not be degraded by a rewrite.
    service = make_rag_service()
    assert await service._contextualize("How do I do addition?", []) == "How do I do addition?"


async def test_contextualize_makes_no_model_call_without_history(monkeypatch):
    calls = {"count": 0}

    def counting_model(*_args, **_kwargs):
        calls["count"] += 1
        raise AssertionError("no model call expected without history")

    import app.services.rag_service as module
    monkeypatch.setattr(module, "create_chat_model", counting_model)

    service = make_rag_service()
    await service._contextualize("How do I do addition?", [])
    assert calls["count"] == 0


async def test_contextualize_rewrites_using_history():
    service = make_rag_service()
    history = [
        ChatMessage(role="user", content="What is this video about?"),
        ChatMessage(role="assistant", content="Getting started with Python."),
    ]
    # The fake model returns a fixed standalone question; the assertion is that the
    # rewritten text is used, not that any particular wording is produced.
    rewritten = await service._contextualize("And what does it use?", history)
    assert rewritten != "And what does it use?"
    assert rewritten.strip()


async def test_contextualize_falls_back_to_the_original_when_the_model_fails():
    # An enhancement must not be able to prevent an answer.
    service = make_rag_service(failing_rewrite=True)
    history = [ChatMessage(role="user", content="anything"), ChatMessage(role="assistant", content="anything")]
    assert await service._contextualize("and the next one?", history) == "and the next one?"


async def test_contextualize_falls_back_when_the_model_returns_blank():
    service = make_rag_service(rewrite_returns="   ")
    history = [ChatMessage(role="user", content="anything"), ChatMessage(role="assistant", content="anything")]
    assert await service._contextualize("and the next one?", history) == "and the next one?"
```

`make_rag_service` stands for whatever helper the file already uses; adapt to it, and
add the `failing_rewrite` / `rewrite_returns` hooks in whatever way fits its existing
fakes.

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest tests/test_rag_service.py -v -k contextualize
```
Expected: FAIL — `AttributeError: 'RAGService' object has no attribute '_contextualize'`.

- [ ] **Step 3: Implement**

```python
CONTEXTUALIZE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Rewrite the user's latest question into a standalone search query for a "
            "video transcript, resolving pronouns and references using the conversation. "
            "Use ONLY information present in the conversation - never invent topics, "
            "names or details that were not mentioned. If the question is already "
            "self-contained, return it unchanged. Reply with the query and nothing else.",
        ),
        ("human", "Conversation:\n{history}\n\nLatest question:\n{question}"),
    ]
)


async def _contextualize(self, message: str, history: list[ChatMessage]) -> str:
    """Rewrite a follow-up into a standalone search query.

    Returns `message` unchanged when there is no history to resolve against, and
    falls back to it if the rewrite fails or comes back empty: retrieval quality is
    an enhancement, and it must never be able to prevent an answer.
    """
    if not history:
        return message

    try:
        chain = CONTEXTUALIZE_PROMPT | self.create_chat_model(streaming=False)
        response = await chain.ainvoke(
            {"history": format_memory(history), "question": message},
            config={"run_name": "contextualize_query", "tags": ["rag", "query-rewrite"]},
        )
        rewritten = str(response.content).strip()
    except Exception as exc:  # noqa: BLE001 - see below
        logger.warning(
            "Query contextualization failed for session; searching with the raw "
            "message instead: %s",
            exc,
        )
        return message

    if not rewritten:
        logger.warning("Query contextualization returned empty text; using the raw message.")
        return message

    logger.info("Contextualized query: %r -> %r", message, rewritten)
    return rewritten
```

**On the broad `except`:** this is one of the few places it is right. The call goes to a
third-party model provider through LangChain, which can raise almost anything — timeouts,
rate limits, provider-specific errors, parsing failures. The fallback is to the exact
behaviour that exists today, so no failure mode is made worse by catching broadly. Every
catch is logged, so nothing disappears silently. Add the `noqa` comment explaining this,
or a reviewer will rightly flag it.

- [ ] **Step 4: Verify**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
```
Expected: **206 passed, 1 skipped** (201 + 5).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rag_service.py backend/tests/test_rag_service.py
git commit -m "feat: rewrite follow-up questions into standalone search queries"
```

---

### Task 5: Wire it into retrieval

**Files:**
- Modify: `backend/app/services/rag_service.py`
- Test: `backend/tests/test_rag_service.py`

- [ ] **Step 1: Write the failing test**

The assertion that matters most in this whole plan:

`test_rag_service.py` already has `make_rag_service(memory)` and patches
`service.create_chat_model` with `lambda streaming: FakeListChatModel(responses=[...])`.
`FakeListChatModel` returns its responses **in order**, which is exactly what is needed
here: the rewrite call consumes `responses[0]` and generation consumes `responses[1]`.

Add two helpers near the existing `FakeVectorStoreService`:

```python
class CapturingVectorStoreService:
    """Records the query it was searched with."""

    def __init__(self) -> None:
        self.last_query: str | None = None

    async def similarity_search(self, query, limit=5, video_id=None):  # noqa: ANN001
        self.last_query = query
        return [make_result()]

    async def upsert_chunks(self, chunks):  # noqa: ANN001
        return [c.chunk_id for c in chunks]


class CapturingChatModel(FakeListChatModel):
    """FakeListChatModel that records every prompt it is invoked with."""

    prompts: list[str] = []

    def _call(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        type(self).prompts.append("\n".join(str(m.content) for m in messages))
        return super()._call(messages, stop=stop, run_manager=run_manager, **kwargs)
```

Then the two tests:

```python
async def test_search_receives_the_rewritten_query(monkeypatch) -> None:  # noqa: ANN001
    memory = InMemoryConversationStore()
    session = memory.create_session_id()
    await memory.append_exchange(session, "What is this video about?", "Getting started with Python.")

    store = CapturingVectorStoreService()
    service = make_rag_service(memory)
    service.vectorstore = store
    monkeypatch.setattr(
        service,
        "create_chat_model",
        lambda streaming: FakeListChatModel(
            responses=["which code editor does the tutorial use", "a grounded answer"]
        ),
    )

    await service.answer(message="And what does it use?", video_id="vid1", session_id=session, top_k=3)

    assert store.last_query == "which code editor does the tutorial use"


async def test_generation_receives_the_original_question_not_the_rewrite(monkeypatch) -> None:  # noqa: ANN001
    """The rewrite is for retrieval only.

    Feeding it into generation would answer a question the user never asked - and a
    rewrite is a guess about intent, not a statement of it. This test is what stops
    someone later "simplifying" the code by passing the rewrite straight through.
    """
    memory = InMemoryConversationStore()
    session = memory.create_session_id()
    await memory.append_exchange(session, "What is this video about?", "Getting started with Python.")

    service = make_rag_service(memory)
    service.vectorstore = CapturingVectorStoreService()
    CapturingChatModel.prompts = []
    monkeypatch.setattr(
        service,
        "create_chat_model",
        lambda streaming: CapturingChatModel(
            responses=["which code editor does the tutorial use", "a grounded answer"]
        ),
    )

    await service.answer(message="And what does it use?", video_id="vid1", session_id=session, top_k=3)

    # prompts[0] is the rewrite call, prompts[1] is generation.
    generation_prompt = CapturingChatModel.prompts[1]
    assert "And what does it use?" in generation_prompt
    assert "which code editor does the tutorial use" not in generation_prompt
```

If `CapturingChatModel` does not hook cleanly into the installed LangChain version,
capture the prompt some other way rather than dropping the assertion — it is the most
important test in this plan.

- [ ] **Step 2: Implement**

In `prepare_context`, contextualize before searching. The history is already loaded
there since Phase 3, so no extra database round trip is added:

```python
        history = await self._get_messages(active_session_id)
        search_query = await self._contextualize(message, history)
        retrieved_context = await self.vectorstore.similarity_search(
            query=search_query,
            limit=top_k,
            video_id=video_id,
        )
```

Check whether `prepare_context` already loads the history; if it does not, load it once
and pass it on rather than reading twice.

- [ ] **Step 3: Verify**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
cd frontend && npx tsc --noEmit && npm test
```
Expected: backend **208 passed, 1 skipped**; frontend **79 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend
git commit -m "feat: search with the contextualized query, answer the original question"
```

---

### Task 6: Measure again (operator)

- [ ] **Step 1: Re-run the evaluation**

Same command as Task 3.

- [ ] **Step 2: Compare against the baseline**

- The "what did you just say it uses" case should now **HIT** on the chunk containing
  `pycharm`.
- The two first-turn cases must **still HIT**, at the same or better rank. A regression
  there means the rewrite is touching queries it should have left alone — check that
  the no-history early return is actually taken.
- The vague case may go either way. Note what the rewritten query was: if the model
  invented a topic the conversation never mentioned, that is the hallucination risk
  materialising and worth recording even if the case happens to hit.

- [ ] **Step 3: Record both runs**

Put the before and after tables in `.superpowers/sdd/progress.md`. A hit rate with no
baseline beside it says nothing.

---

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md` (on disk; gitignored), `AGENTS.md`

- [ ] **Step 1: Document the behaviour**

Add to the Configuration or Architecture section of both: follow-up questions are
rewritten into standalone search queries using the conversation history before
retrieval; first turns are not rewritten; a failed rewrite falls back to the raw
message; generation always receives the original question.

Mention `scripts/run_retrieval_eval.py` and that it needs an ingested video plus
`DATABASE_URL`.

Update the test counts to whatever the suite reports.

- [ ] **Step 2: Verify and commit**

```bash
cd backend && OPENAI_API_KEY=dummy python -m pytest -q
git add AGENTS.md
git commit -m "docs: record contextualized retrieval and its evaluation runner"
```

---

## What this plan deliberately does not do

- **Does not add a summarisation path** for broad questions like "what is this video
  about". Those are not retrieval questions; that is a separate feature.
- **Does not tune `CHUNK_MAX_CHARS` or `top_k`.** This work creates the baseline that
  makes tuning measurable rather than guessed — using it is the next change, not this
  one.
- **Does not add reranking or hybrid search.**
- **Does not extend the existing answer-quality evaluation.** It measures a different
  stage and cannot express a conversation.
