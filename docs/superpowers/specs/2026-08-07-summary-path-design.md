# A summarisation path for broad questions — design

- **Date:** 2026-08-07
- **Branch:** `quality/contextualized-retrieval` (or a successor)
- **Status:** Approved design, not yet planned or implemented
- **Predecessor:** the contextualized-retrieval work (`dc78b81` and earlier), which
  deliberately excluded this and left the evidence for it

## The problem

*"What is this video about?"* asks about the whole, not a passage. Top-k retrieval
answers it by construction badly: it picks five chunks and hopes they represent
ten minutes of video.

This is measured, not asserted. In the retrieval evaluation the broad question's
best match scored **0.66 cosine distance** — the weakest on-topic score recorded,
against 0.48–0.53 for passage questions. `first-list` ("How do I create a list?")
sits at the same 0.66 and is documented in the fixture as "the case most likely
to break first". Broad questions live permanently in that weak band, and no
amount of retrieval tuning moves them: the `CHUNK_MAX_CHARS` and `top_k` sweeps
both concluded that the passage-retrieval machinery is already at a sensible
operating point.

The original retrieval spec named this and excluded it: *"Broad questions are not
retrieval questions… that needs a summarisation path, which is a different
feature."* This is that feature.

## Decisions taken during brainstorming

### 1. Detection is automatic, via a heuristic with no model call

The user chose automatic detection over an explicit UI button. That is the higher
risk option and the risk was stated: a misclassification sends an ordinary
question down the wrong path, adding a new failure source to the chain this
project just spent a full cycle repairing.

The risk is contained by *how* detection works. A **pure pattern-matching
function** — no model call, no I/O — keeps three properties that an LLM
classifier would cost:

- **Deterministic.** The fixture work removed a noise source larger than the
  effect being measured. An LLM classifier would reintroduce exactly that.
- **Free and instant.** No added latency on a Render free tier that already has a
  30–60 s cold start.
- **It preserves a documented invariant.** `_contextualize` guarantees *no
  history → no model call*, with a test. Broad questions are typically FIRST
  turns, so an LLM classifier would break that guarantee precisely where it
  matters most.

The cost is real and should not be glossed: a heuristic recognises only what
someone thought of. Unusual phrasings fall through to the normal path — which is
today's behaviour, so a miss is not a regression.

### 2. One model call over the whole transcript

Chosen over map-reduce across chunks. The two evaluation videos are 10k and 14k
characters, roughly 3–4k tokens: comfortable for `gpt-4o-mini` in a single call.
Map-reduce would scale to arbitrary length and yield timestamps for free, but at
N+1 model calls — 29 calls for the biology video.

The stated cost of this choice is that **long videos do not fit**. A two-hour
video is easily 200k characters and would exceed the context window. This design
does not add map-reduce; it adds a length guard that degrades to the normal path
rather than crashing (see Error handling). Map-reduce remains the answer if long
videos ever matter.

### 3. The transcript is fed WITH timestamps, and the model must cite them

Timestamped citations are the product's identity. A summary built from a
plain-text transcript could not carry them.

Feeding the transcript as timestamped sections and instructing the model to
attach a time mark to each point recovers the promise for the price of a longer
prompt. The obvious hazard — the model inventing time marks — is handled by
validating every mark against the transcript before it becomes a citation.

### 4. The full transcript comes from the vector store, not from YouTube

The `VectorStore` protocol currently exposes only `replace_video_chunks` and
`similarity_search`; there is no way to read all of a video's chunks. This design
adds one:

```python
async def list_video_chunks(self, video_id: str) -> list[TranscriptChunk]: ...
```

implemented in both backends with contract tests — the pattern this codebase has
already used twice.

The alternative, re-fetching from YouTube on the request path, was rejected: it
502s from Render's datacenter IPs without the Webshare proxy and is slow with it.
A summary would then fail for a video that is demonstrably already ingested,
which is the worst kind of failure — one the user cannot understand.

Chunks overlap by one segment, so reconstruction must deduplicate using
`segment_indices` or the boundary segment appears twice.

## Goals

1. A broad question produces an overview of the whole video rather than five
   arbitrary passages.
2. That overview carries verifiable timestamps.
3. **No ordinary question changes behaviour.** This is the primary constraint,
   not a secondary one.
4. Public API contract, response schema and the frontend unchanged.
5. Deployment stays at **$0/month**.

## Non-goals

- Map-reduce summarisation of long videos.
- An LLM-based classifier.
- Judging summary *quality* automatically (see Testing).
- Applying the path to `agent_service`, which has its own tool loop and would
  need its own decision.
- Any frontend change.

## Architecture

Three units, each with one job:

| Unit | Responsibility | Depends on |
|---|---|---|
| `is_broad_question(message) -> bool` | classify, purely | nothing |
| `VectorStore.list_video_chunks(video_id)` | read every chunk of one video | the store |
| `RAGService.summarize_video(...)` | produce the summary and its citations | the two above, the chat model |

### Where the branch sits

At the top of `answer()` and `stream_answer()`, **not** inside `prepare_context`.
A summary replaces both retrieval and generation, so branching inside the
retrieval helper would be the wrong level.

```
answer(message, video_id, session_id, top_k)
├─ is_broad_question(message) and video_id is not None
│   ├─ yes → summarize_video(...)          [falls back to the branch below on any failure]
│   └─ no  → _contextualize → similarity_search → RAG_PROMPT   (unchanged)
```

`stream_answer()` takes the same branch and emits the summary as a single `token`
event: the model call is not streamed, so pretending otherwise would only add
machinery.

### `summarize_video`, step by step

1. `chunks = await vectorstore.list_video_chunks(video_id)`
2. Reconstruct the transcript ordered by chunk index, deduplicating overlap via
   `segment_indices`, prefixing each section with `MM:SS`
3. If the reconstructed text exceeds **40,000 characters** (roughly 10k tokens,
   about a 40-minute video at these transcript densities), give up and fall
   through to the normal path. The number is a judgement, not a measurement: it
   sits far above both evaluation videos and far below `gpt-4o-mini`'s context
   limit, leaving room for the prompt and the answer.
4. One chat call with `SUMMARY_PROMPT`
5. Parse `MM:SS` / `HH:MM:SS` marks from the answer; keep only those inside the
   video's real time range that map to an existing chunk
6. Build `TimestampCitation` objects from the surviving marks

### What the response looks like

`RAGChatResponse`, unchanged: `answer`, `citations`, `retrieved_context`,
`memory`. The frontend already renders citations as clickable time marks, so it
needs no change.

`retrieved_context` is **empty**. No chunk selection took place, and populating it
with the chunks that happened to feed the summary would misrepresent what the
system did. An empty list is the honest answer to "which passages was this
grounded in" when the answer is "all of them".

## Error handling

**The summarisation path degrades; it does not fail.** This follows the asymmetry
already established twice in this codebase: retrieval fails loudly with a 502
because retrieval *is* the product, while conversation memory and the query
rewrite degrade because they are enhancements. A summary is an enhancement — when
it fails, the question goes down the normal path and gets the answer it would
have got before this feature existed.

| Failure | Behaviour |
|---|---|
| Transcript over 40,000 characters | normal path, logged with the measured length |
| Model call raises or times out | normal path, logged |
| Model returns blank | normal path, logged |
| Video has no chunks | normal path, which answers honestly that it cannot |

The broad `except` around the model call is justified the same way as in
`_contextualize`: the call reaches a third-party provider through LangChain and
can raise almost anything, and the fallback is behaviour that already exists, so
no failure mode is made worse by catching broadly. Every catch is logged.

**Timestamp validation is not error handling but anti-hallucination.** A mark
outside the video's range, or one that matches no chunk, is dropped from the
citation list and logged. The answer text may still mention it; what matters is
that we never attach a citation object to a time that does not exist.

## Testing

### The strongest test already exists

**None of the 26 content cases in `retrieval_eval_cases.json` may classify as
broad.** Those cases were written for a different purpose and happen to be the
exact corpus needed here: real questions, two videos, five kinds. The check runs
offline, costs nothing, and guards precisely the risk that automatic detection
introduces. It goes in `test_retrieval_eval_fixture.py` alongside the existing
fixture checks.

A companion list of genuinely broad questions must classify as broad — including
the German phrasings the app is used with, since the heuristic is
pattern-matching and language coverage is a deliberate choice rather than an
emergent property.

### The rest

- `is_broad_question` unit tests in both directions, including near-misses
  ("what does the video say about loops" is NOT broad).
- A test that the heuristic triggers **no model call**, mirroring
  `test_contextualize_makes_no_model_call_without_history`.
- `list_video_chunks` joins the existing vector-store contract suite, so both
  backends are proven to behave identically before either is relied on.
- Transcript reconstruction deduplicates overlap: a unit test over a known chunk
  set with a shared boundary segment.
- Timestamp validation drops out-of-range and unmatched marks: a unit test with a
  fabricated model answer containing one valid and two invalid marks.
- The summary path degrades to the normal path when the model fails, in both
  `answer()` and `stream_answer()`.

### What cannot be tested, stated plainly

**Whether a summary is good.** There is no ground truth for it, and inventing one
would produce a number that looks like evidence and is not. Judging summary
quality needs an LLM judge, which is its own feature with its own failure modes.
What this design can and does measure: classification, citation validity, and
degradation.

## Definition of done

- `cd backend && python -m pytest` → green, count reported as measured
- `cd frontend && npx tsc --noEmit && npm test` → **79 passed**, unchanged
- The 26 content cases all classify as not-broad, asserted by a test
- A broad question against an ingested video returns an overview whose timestamps
  all resolve to real positions in that video
- No ADDITIONAL model call on any question that is not broad. Follow-ups still
  make the one rewrite call they make today; what must not appear is a second
  one introduced by this feature.

## Open risks

**The heuristic's coverage is its weakness, by construction.** It recognises the
phrasings someone listed. The mitigation is that a miss degrades to today's
behaviour rather than to something worse — but a user who phrases the question
unusually gets the weak answer and no indication why.

**Timestamp validity is not timestamp correctness.** A mark can be inside the
video and match a chunk while still pointing at the wrong moment. Validation
catches invention, not misattribution. Detecting misattribution would need the
LLM judge this design excludes.

**One model call over a whole transcript is a large prompt.** At 14k characters
the biology video is fine; the length guard exists because the next video might
not be. The guard's threshold is a judgement, not a measurement, and the first
video that trips it will be the one that tells us whether it was set sensibly.
