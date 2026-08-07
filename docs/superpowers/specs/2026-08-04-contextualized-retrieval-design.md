# Contextualized retrieval for follow-up questions — design

- **Date:** 2026-08-04
- **Branch:** `quality/contextualized-retrieval`
- **Status:** Approved design, not yet planned or implemented
- **Predecessor:** Phase 3 (`cfe0bd5`) — conversation history persists, which is what makes this possible

## The observed failure

During Phase 3 verification, two turns in one session:

```
[user]      What is this video about?
[assistant] This video is about getting started with Python in less than 10 minutes…
[user]      And what did you just say it uses?
[assistant] Functions are used to reuse your code in many different instances…
```

The second answer is unrelated to the question. It is **not** a generation problem — the
answer is faithfully grounded in the chunks it was given. The retrieval brought back
the wrong chunks.

## Root cause

`rag_service.prepare_context` embeds the raw user message:

```python
retrieved_context = await self.vectorstore.similarity_search(
    query=message,          # the raw user message
    limit=top_k,
    video_id=video_id,
)
```

*"And what did you just say it uses?"* contains **no information about the video**. It
is pure conversational reference. Its embedding points at generic conversational
language and matches nothing specific in a transcript, so the nearest neighbours are
effectively arbitrary.

The conversation history *is* available — it is injected into the generation prompt.
But that happens **after** retrieval. For the search itself, the history does not exist.

Phase 3 is what makes the fix possible: before it, history was per-process and lost on
restart, so building retrieval on top of it would have been unreliable.

## Two related findings, deliberately out of scope

Recorded so they are not rediscovered as surprises:

**Broad questions are not retrieval questions.** *"What is this video about?"* asks
about the whole, not a passage. Its best match scored 0.66 cosine distance — weak for
`text-embedding-3-small`. Top-k chunks cannot answer it well by construction; that
needs a summarisation path, which is a different feature.

**`CHUNK_MAX_CHARS=1200` is on the large side.** More text per chunk means a blurrier
embedding. Worth tuning, but tuning without a baseline is guessing — which is precisely
what the measurement in this spec exists to fix. A future change can use it.

## Decisions taken during brainstorming

### 1. Rewrite only when there is history

`_contextualize` returns the message **unchanged** when the session has no prior
messages. The first question of a session therefore costs no extra call and cannot be
degraded by a rewrite.

This matters beyond cost: query rewriting can make a good query worse. Restricting it
to the case it was designed for — messages that reference earlier turns — bounds that
risk to where the benefit is.

### 2. Failure falls back to the raw message

If the rewrite call fails or times out, retrieval proceeds with the original message.
The same principle as conversation memory in Phase 3: an enhancement must not be able
to prevent an answer. A failed rewrite degrades quality back to today's behaviour,
which is the worst acceptable outcome.

### 3. The rewritten query is logged

Without it, a future bad retrieval is undiagnosable — you would see the user's question
and the returned chunks with no way to know what was actually searched for.

### 4. The measurement targets retrieval, not generation

The project already has `scripts/run_evaluation.py`, `/api/evaluations/rag` and
`tests/fixtures/rag_eval_cases.json`. That machinery scores **answers** — groundedness,
hallucination risk, citation quality, latency.

It is the wrong instrument here, for two reasons:

- **It measures the wrong stage.** In the observed failure the answer was faithfully
  grounded in the chunks it received. An answer-quality score would not have flagged
  it.
- **It cannot express the failing case.** `RAGEvaluationRequest` carries a single
  `message`. Follow-up questions need a conversation, which the existing case format
  has no way to represent.

So this adds a separate, smaller instrument: cases that are **conversations**, scored
on whether the expected chunk appears in the top-k and at what rank. No LLM judge,
deterministic, and cheap enough to run on every change.

**It also guards the risk in decision 1**: the case set includes first-turn questions,
so a rewrite that degrades them shows up as a regression rather than going unnoticed.

## Goals

1. Follow-up questions retrieve chunks relevant to what the user actually means.
2. First-turn retrieval is measurably not worse.
3. A retrieval baseline exists that future chunking or `top_k` changes can be measured
   against.
4. Public API contract, response schemas and the frontend unchanged.
5. Deployment stays at **$0/month**.

## Non-goals

- A summarisation path for broad questions.
- Chunking or `top_k` tuning — enabled by this work, not part of it.
- Reranking or hybrid search.
- Replacing or extending the existing answer-quality evaluation.

## Architecture

### The rewrite step

In `rag_service.py`:

```python
async def _contextualize(self, message: str, history: list[ChatMessage]) -> str:
    """Rewrite a follow-up into a standalone search query.

    Returns `message` unchanged when there is no history, when the rewrite fails,
    or when the model returns something empty.
    """
```

Called from `prepare_context` before `similarity_search`. The history is already loaded
there after Phase 3, so no additional database round trip is introduced.

The prompt instructs the model to resolve references using the history and to return
**only** the rewritten question — and to return the original unchanged if it is already
self-contained. It uses the configured chat model, so the `LLM_PROVIDER` switch keeps
working.

### What the generation prompt receives

Unchanged: the generation step still sees the **original** user message and the full
history. Only the retrieval query is rewritten. Feeding a rewritten question into
generation would risk answering a question the user did not ask.

### Cost and latency

One extra LLM call per follow-up turn, on the request path. Roughly 300–800 ms against
a turn that already takes seconds. First turns are unaffected.

This is a real cost on the critical path and the reason the rewrite is skipped when it
cannot help.

## The measurement

### Case format

A new `tests/fixtures/retrieval_eval_cases.json`, separate from `rag_eval_cases.json`
because the shape differs:

```json
{
  "video_id": "fWjsdhR3z3c",
  "cases": [
    {
      "name": "follow-up referring to the previous answer",
      "history": [
        {"role": "user", "content": "What is this video about?"},
        {"role": "assistant", "content": "This video is about getting started with Python…"}
      ],
      "question": "And what did you just say it uses?",
      "expect_chunk_containing": "<see below — must be derived, not invented>"
    }
  ]
}
```

`expect_chunk_containing` is a substring that must appear in a retrieved chunk's text.
Matching on text rather than chunk ids is deliberate: chunk ids derive from chunking
parameters, so an id-based expectation would break the moment someone tunes
`CHUNK_MAX_CHARS` — exactly the change this baseline is meant to enable.

**The expected substrings must be read out of the actual ingested chunks, not guessed.**
Nobody writing this spec has seen the transcript of `fWjsdhR3z3c`. An invented
expectation would produce a case that fails for the wrong reason — or worse, passes
because the substring happens to appear in an irrelevant chunk — and would quietly
discredit the whole baseline.

The first step of implementation is therefore to dump the ingested chunks for the video
and choose substrings from them, one per case, each specific enough that only the
intended chunk contains it.

### Metrics

Per case: whether an expected chunk is in the top-k (hit), its rank, and the best
distance. Reported as a table plus a hit-rate total.

### Runner

`scripts/run_retrieval_eval.py`, alongside the existing evaluation script. It needs an
ingested video and a database, so it is operator-run, not part of the test suite.

**It calls `prepare_context` in-process**, not the HTTP API. Two reasons: it needs the
retrieved chunks with their distances, which the chat response does not expose in the
form needed; and going in-process means the rewrite step is exercised exactly as
production runs it, rather than through a route that could differ.

It constructs the service with a `ConversationStore` pre-loaded with each case's
`history`, so the conversation is set up without needing to replay turns through the
LLM — the point is to measure retrieval, and generating the assistant's side of the
history would cost money and add noise.

## Testing

- `_contextualize` returns the message unchanged with empty history — no LLM call made.
- With history, it calls the model and returns the rewritten text.
- A failing model call returns the original message and logs.
- An empty or whitespace-only model response returns the original message.
- The generation prompt still receives the original message, not the rewrite.

The last one matters: it is the assertion that stops someone later "simplifying" the
code by passing the rewritten question through to generation.

## Definition of done

- `cd backend && python -m pytest` → green
- `cd frontend && npx tsc --noEmit && npm test` → **79 passed**
- Baseline recorded **before** the rewrite is implemented, and the after-run shows the
  follow-up cases hitting where they previously missed
- First-turn cases show no regression in hit rate

## Open risks

**A rewrite can hallucinate specifics.** Asked to make *"and the second one?"*
standalone, a model may invent a topic the conversation never mentioned, sending
retrieval somewhere confidently wrong. The prompt constrains it to the history, and the
measurement will show it — but the case set must include a vague follow-up
specifically to expose it.

**The baseline is one video.** `fWjsdhR3z3c` is short and about Python. Conclusions
drawn from it may not generalise. Enough to detect a regression, not enough to claim a
general improvement — and the spec says so rather than implying more.
