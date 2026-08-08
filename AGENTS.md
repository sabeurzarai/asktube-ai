# AskTube AI — project context for Codex

AI-powered YouTube learning app: search videos, ingest transcripts into a vector
store, chat with timestamped citations. Ironhack final project, now a live demo.

**Read `LEARNINGS.md` before making changes** — it records hard-won gotchas
(pydantic-settings env parsing, YouTube IP blocking, DNS cutover pitfalls,
test-environment quirks). Add new lessons there, one dated bullet each.

## Live deployment ($0/month)

| Piece | Where |
|---|---|
| Frontend (Next.js) | Vercel — https://asktube-ai.duckdns.org + https://asktube-ai.vercel.app |
| Backend (FastAPI, Docker) | Render free tier — https://asktube-ai-q2gi.onrender.com |
| Vector store | Postgres + pgvector, via `DATABASE_URL` (ChromaDB removed) |
| Conversation history | Postgres (`conversation_messages` table), via `DATABASE_URL` |
| DNS | DuckDNS A record → Vercel IP (duckdns is PSL-listed, so Vercel treats it as apex) |

- **Push to `main` auto-deploys BOTH platforms.** A broken push takes down the live demo.
- Render root dir = `backend/`, Docker runtime (ffmpeg included), `PORT=8000`.
- Vercel root dir = `frontend/`; `NEXT_PUBLIC_API_URL` is baked at build time —
  changing it requires a redeploy, not just saving the variable.
- Render free tier: sleeps after 15 idle min (30–60 s cold start); **no persistent
  disk**, but transcript vectors and conversation history both now live in Postgres
  and survive a restart — verified live for vectors (ingest → restart → same query
  returns identical chunks/ids/distances, no re-ingest needed). SQLite analytics
  still resets on restart. Warm `/health` before presenting; re-ingesting is no
  longer required.
- YouTube blocks transcript fetches from datacenter IPs: `WEBSHARE_PROXY_URL`
  (residential proxy) must be set on Render or ingestion 502s.

## Configuration

- Chat provider switch: `LLM_PROVIDER=openai|nvidia` — factory in
  `backend/app/services/llm_provider.py`. NVIDIA (NIM, OpenAI-compatible) replaces
  chat only; embeddings + Whisper ALWAYS use OpenAI (`OPENAI_API_KEY` required in
  every mode). `NVIDIA_TOOL_CALLING=false` makes the agent fall back to plain RAG.
- Embeddings switch: `EMBEDDING_PROVIDER=openai|local` — factory in
  `backend/app/services/embedding_provider.py`. Local mode needs opt-in extras
  (`pip install -r backend/requirements-local-embeddings.txt`, torch is
  platform-specific — see that file) and a wiped + re-ingested vector store.
- `CORS_ORIGINS` accepts JSON array, comma-separated, or single origin (the field
  uses `NoDecode` — do not remove it, plain values crash startup otherwise).
- Vector store: **ChromaDB is gone** — no `chromadb` dependency, no
  `ChromaVectorStoreService`, no `chroma_data` directory. `VECTOR_BACKEND` accepts
  `pgvector` or `memory` only; factory in `backend/app/services/vector_store/factory.py`.
  `chroma` now raises a `ValueError` naming it as removed rather than falling into
  the generic unknown-backend error. Unset `VECTOR_BACKEND` derives the backend from
  `DATABASE_URL`: set → `pgvector`, absent → `memory` — this is why forgetting the
  variable in a deployment that has a database no longer silently produces an
  ephemeral store. `VectorStoreService` in `vectorstore_service.py` owns embedding
  generation and delegates persistence to the selected store.
  `VECTOR_COLLECTION_NAME` (default `asktube_videos`) is the logical name reported
  as `collection_name` in API responses. `CHROMA_COLLECTION_NAME` survives only as
  a compatibility fallback for already-deployed environments that still set it —
  it is not the setting to use going forward.
  **Re-ingesting a video always REPLACES its chunks rather than upserting** — this
  is now unconditional, since the Chroma path that still upserted no longer exists.
- Local development: `docker compose up` starts a `postgres` service on
  `pgvector/pgvector:pg16` (no more chromadb container), and the backend gets
  `DATABASE_URL` pointing at it. Migrations run once, manually:
  `docker compose exec backend python -m alembic upgrade head`.
- Database: `DATABASE_URL` is the single async SQLAlchemy URL for all persistent
  stores and takes priority over `ANALYTICS_DATABASE_URL`. Unset, everything runs
  on SQLite as before. Postgres schema is owned by Alembic — run migrations
  against the direct/session endpoint (port 5432), NOT the Supavisor transaction
  pooler (port 6543) the running app uses: `cd backend && python -m alembic
  upgrade head`. `init_analytics_db()` auto-creates tables for SQLite only.
  Migrations are a manual pre-deploy step — the Docker image ships `alembic.ini`
  and `alembic/`, but nothing runs them automatically at container start.
  Every Postgres engine (app AND Alembic, unconditionally — not just when a
  pooler is in front) sets three asyncpg connect args: `statement_cache_size=0`,
  `prepared_statement_cache_size=0`, and a UUID-based
  `prepared_statement_name_func`. `statement_cache_size=0` alone is NOT enough —
  it only disables asyncpg's own cache, while SQLAlchemy's asyncpg dialect keeps
  a second prepared-statement layer (its own cache size, defaulting to 100, plus
  a numeric name generator) that still needs disabling, or pooled connections
  collide with `DuplicatePreparedStatementError`.
- Conversation memory: `CONVERSATION_BACKEND` accepts `postgres` or `memory`;
  factory in `backend/app/services/conversation_store/factory.py`. Unset derives
  the backend from `DATABASE_URL`: set → `postgres`, absent → `memory` — same
  pattern as `VECTOR_BACKEND`. History is trimmed to the newest 8 messages per
  session on write, inside the insert's transaction — this mirrors the bounded
  deque the in-process store always used, so nothing is lost that would not
  already have been discarded before. **Memory degrades, it does not fail**: if
  the store is unreachable, `RAGService` logs a warning and answers with empty
  history instead of erroring — deliberately the opposite of retrieval, which
  fails loudly with a 502, since retrieval is the product and memory is only an
  enhancement. The in-memory implementation stays permanently as the dev/CI
  backend — unlike ChromaDB it is not being removed — so
  `CONVERSATION_BACKEND=memory` remains a supported rollback. Migration `0003`
  creates `conversation_messages`; run migrations with `cd backend && python -m
  alembic upgrade head`.
- Retrieval query contextualization: `RAGService.prepare_context` does **not**
  embed the raw user message. It loads the conversation history once, and
  `_contextualize` rewrites a follow-up into a standalone search query before
  the vector search. Three rules, each with a test guarding it:
  **no history → no rewrite and no model call** (a first turn has nothing to
  resolve against, so a rewrite could only make a good query worse);
  **rewrite failure or blank response → the raw message** (retrieval quality is
  an enhancement and must never prevent an answer — same degrade-not-fail
  principle as conversation memory);
  **generation always receives the ORIGINAL question**, never the rewrite — a
  rewrite is a guess about intent, and answering it would answer a question the
  user never asked. `prepare_context` returns `(session_id, context, history)`
  so callers reuse that history instead of re-reading it; do not reintroduce a
  second read. Cost: one extra chat call per follow-up turn, none on first
  turns.
- Chunk size: `CHUNK_MAX_CHARS` defaults to **600**, lowered from 1200 on
  2026-08-06. The justification is the **context share**, not the hit rate: at
  1200 the top-5 chunks of a 10k-character video handed the model 53% of the
  whole transcript, which undercuts the prompt's promise to answer only from the
  provided context; 600 halves that to 29% with no loss of hit rate. The 5-case
  eval set could **not** discriminate chunk sizes — everything from 450 upward
  scored 5/5, and its run-to-run noise (one case, from the non-deterministic
  rewrite) exceeded the difference being measured.
  The hardened set, run frozen, is deterministic — two consecutive sweeps are
  bit-identical — and on the FIRST video alone it appeared to confirm 600 (18/18
  against 17/18 everywhere else).
  Adding the second video WITHDREW that confirmation for a while — 600 and 1200
  tied at 28/29 — and that withdrawal was the more useful result at the time,
  because it exposed an over-claim drawn from a single video.
  **The tie has since been resolved, and not by tuning:** `bio-vague-first` was
  found to be demanding worse behaviour than the system produced. Its history said
  only that photosynthesis has two kinds of reactions, so "and what happens first?"
  could mean the first stage or the first event inside it; the rewrite chose the
  former and retrieval correctly returned the overview passage at rank 1. The case
  was under-anchored, not the retrieval wrong. With the history naming the
  light-dependent reactions, the current picture is **600: 29/29, 450 and 1200:
  28/29, 900: 27/29** — 600 is the only size with a clean sweep.
  Read that carefully: the retarget was decided from a rank-1 result at 600 alone,
  with no reference to the other sizes, so 600's improved score is a consequence
  rather than the motive. The primary justification for the default is still the
  **context share** (600: 29%/20% of each video, 1200: 53%/41%) and the normalised
  rank, both arithmetic and independent of any case set.
  Which cases fail still carries signal: `first-power` (vocabulary mismatch) fails
  only at 1200, where the coarse chunk dilutes the passage; `vague-branches` fails
  at 450 and 900.
  `scripts/sweep_chunk_size.py` re-runs the comparison; it reports normalised rank
  and context share because raw mean rank is not comparable across chunk counts.
  **Already-ingested videos keep their old chunks** until re-ingested — the store
  can hold a mix of 1200- and 600-character chunks, which is harmless for
  retrieval but makes distances across videos non-comparable.
  Four call sites used to hardcode 1200 and ignore the setting
  (`tools/ingest_video.py`, `tools/chunk_transcript.py`, and the `Query` defaults
  in `routes/chunks.py` and `routes/vectorstore.py`); they now read
  `settings.chunk_max_chars`. Two of the four have a regression guard in
  `test_tools.py` that asserts the `ChunkingOptions`/call kwargs against the
  setting rather than a literal (`test_chunk_transcript_calls_service_with_correct_options`
  for `tools/chunk_transcript.py`, `test_ingest_video_chunks_with_configured_chunk_settings`
  for `tools/ingest_video.py` — the one that determines production chunk size on
  the agent path). The two `Query(default=settings.chunk_max_chars)` route
  defaults in `routes/chunks.py` and `routes/vectorstore.py` remain untested: a
  regression there would not be caught by the suite.
- Summarisation path: a **broad** question ("what is this video about?") does not
  go through retrieval. `is_broad_question` in
  `backend/app/services/question_kind.py` classifies it with a **pure pattern
  match — no model call**, deliberately: an LLM classifier would be
  non-deterministic, would add latency to every request, and would break the
  documented guarantee that a first turn makes no model call (broad questions
  are usually first turns). The cost is that only phrasings someone listed are
  recognised; a miss falls through to retrieval, which is the old behaviour, so
  it is never a regression.
  `RAGService.summarize_video` then reads EVERY chunk via the vector store's
  `list_video_chunks`, rebuilds a timestamped transcript and makes **one** chat
  call. Timestamps in the answer are validated against real chunks before
  becoming citations — an invented mark is logged and dropped rather than
  asserted as a source.
  **It degrades, it does not fail**: no chunks, a transcript over
  `SUMMARY_MAX_CHARS` (40,000), a failed or empty model call — each returns
  `None` and the question is answered by retrieval instead.
  `retrieved_context` comes back **empty** on this path, because no chunk
  selection happened. Do not "fix" that by listing the chunks that fed the
  summary.
  The regression guard is free and already written:
  `test_no_content_case_is_classified_as_broad` asserts that none of the 26
  content cases in the retrieval fixture classify as broad.
  Known limits: timestamp **validity** is not timestamp **correctness** — a mark
  can be inside the video and match a chunk while still pointing at the wrong
  moment. And whether a summary is *good* is not measured at all; there is no
  ground truth for it, and inventing a number would produce something that looks
  like evidence and is not.
  Because the branch lives inside `RAGService.answer()`, the agent path
  (`agent_service._answer_via_rag`) and the `answer_question` tool inherit this
  behaviour for free — no separate agent-path wiring was added or is needed.
  This was checked across the consumers of `RAGChatResponse`, not assumed —
  but the first pass missed one of three, and that miss is worth recording
  rather than papering over. `agent_service._answer_via_rag` and the
  `answer_question` tool consume only `answer`, `citations` and `session_id`;
  neither reads `retrieved_context`, and the frontend never references it
  either, so the empty context is harmless there. The third consumer,
  `observability_service.evaluate_response_quality` (used by both
  `/api/evaluations/rag` and `/api/evaluations/conversation`), DOES read
  `retrieved_context` and was missed — the empty list made it score every
  summary answer as ungrounded (groundedness 0.0, hallucination_risk 1.0)
  with a self-contradictory `has_citations=False` next to a nonzero
  `citation_count`. It is fixed now: when `retrieved_context` is empty but
  `citations` is not, `evaluate_response_quality` derives the context text and
  the citation evaluation from the citations instead, mirroring the same
  principle `_record_rag_metrics` already applies via `context_chars`.
- Retrieval measurement: `cd backend && python scripts/run_retrieval_eval.py`
  scores 29 conversation cases across **two videos** in
  `backend/tests/fixtures/retrieval_eval_cases.json` against the deployed store.
  Operator-run — it needs `DATABASE_URL`, `OPENAI_API_KEY` and BOTH videos
  (`fWjsdhR3z3c`, Python tutorial; `sQK3Yr4Sc_k`, Crash Course photosynthesis)
  already ingested. A missing video does not error — its cases just return
  nothing and read as retrieval failures. The second video is deliberately as
  far from programming as possible: with no shared vocabulary, a question the
  Python video answers scores 0.93 against the biology chunks, which is what
  makes the `bio-crossvideo-python` case meaningful — it checks that the
  `video_id` filter really scopes the search.
  **Two modes, and the wrong one makes the numbers meaningless.** Default `live`
  runs the real rewrite, so it judges retrieval as a whole but is not
  reproducible. `--frozen` searches with the `search_query` recorded per case:
  deterministic, no chat calls. Use `--frozen` whenever the variable under test
  is anything OTHER than the rewrite — chunk size, `top_k`, the embedding model
  — because the rewrite's run-to-run swing is larger than those effects and will
  drown them. This is not theoretical: the 5-case predecessor moved by a whole
  case between runs with identical inputs.
  Re-record the frozen queries with `scripts/refresh_frozen_queries.py` after a
  deliberate rewrite change, and **read the diff** — a bad rewrite, once frozen,
  becomes what every later comparison measures.
  Case kinds: `first_turn` (regression guards, no rewrite), `followup_reference`,
  `followup_vague`, `topic_shift` (guards the opposite failure — a rewrite
  dragging stale context into a self-contained question), and `off_topic`, which
  is **scored inverted**: passing means the best distance stayed ABOVE 0.78. Without
  those two, the set could not detect a system that answers confidently from
  irrelevant chunks, because every other case rewards returning something. The
  threshold is measured — on-topic questions score 0.48–0.66, off-topic 0.87–0.94.
  `tests/test_retrieval_eval_fixture.py` validates the fixture offline (no DB, no
  key): every expected substring must identify **exactly one** chunk of ITS OWN video at
  sizes 450, 600, 900 and 1200. That check earned its place — 7 of 20 candidate substrings
  failed it, including `try and accept` and `hey there`, and `convert mario` is
  unique at 450/900/1200 but duplicated at 600 by the overlap segment. An
  ambiguous substring does not fail loudly; it makes its case pass for the wrong
  reason. The transcript is committed at
  `tests/fixtures/transcript_fWjsdhR3z3c.json` so the check needs no network.
- `top_k` stays at **5** — measured with `scripts/sweep_top_k.py`, which
  concluded that the current value is right. Two traps make the naive
  measurement useless, and both are worth knowing before anyone re-opens this:
  **hit rate is monotone non-decreasing in `top_k`** (a larger k can never lose a
  hit, so k = chunk count scores 100% trivially — "higher was better" is
  arithmetic, not a finding); and **`off_topic` cases are invariant to `top_k`**,
  because they score the best/minimum distance, which does not change whether you
  return 1 result or 10. The sweep therefore excludes them and reads the rank
  distribution instead, asking where the curve flattens.
  It flattens immediately: 16 of 26 cases hit at rank 1, and k=4, k=6 and k=7 buy
  nothing at all. Going from 5 to the plateau at 8 buys exactly one case —
  `bio-vague-first`, the one already documented as possibly over-specified —
  while context share rises from 29%/20% to 46%/32%. Rejected. k=3 is the real
  alternative (23/26 at 17%/12%) but costs two sound follow-up cases.
  Like `CHUNK_MAX_CHARS` before it, `top_k` has **no setting**: 5 is a literal in
  `schemas/rag.py`, `schemas/evaluation.py`, `agent_service.py`,
  `tools/answer_question.py` and `frontend/lib/api.ts`. Left alone deliberately —
  introducing a setting whose value you do not want to change is work without
  benefit.
- `scripts/sweep_chunk_size.py` compares chunk sizes on that set, in-process
  against `InMemoryVectorStore` — it never writes to the deployed database.
  Verified faithful: at 1200 it reproduces the pgvector numbers to within float
  noise. It reports normalised rank and context share because raw mean rank is
  not comparable across chunk counts.

## Testing (verify before claiming done)

- Backend: `cd backend && python -m pytest` → expect **280 passed, 1 skipped**
  with local-embedding extras installed (the 1 skip is the Alembic migration
  test, which skips unless `TEST_DATABASE_URL` is set). Without the extras the 4
  local-embedding tests skip instead of running, giving **276 passed, 5
  skipped** — derived from the measured number, not separately measured. Set
  `OPENAI_API_KEY` to any dummy value first or 9 speech tests fail with 503.
  The WARNING count is **not** a regression signal: `test_speech_route.py`
  intermittently emits 0–3 `PytestUnhandledThreadExceptionWarning` from an
  analytics write reaching aiosqlite after the test's event loop closed.
- Frontend: `cd frontend && npx tsc --noEmit && npm test` → expect **79 passed**.
- Frontend voice tests stub `@/lib/api` wholesale with `vi.mock` — `lib/analytics.ts`
  must NOT import from `lib/api.ts` (duplicate the resolver logic, keep in sync).

## History (short)

Originally deployed on EC2 (terminated July 2026, Elastic IP released). The repo
previously lived at a deeply nested Windows path — moved here 2026-07-05. Full
deployment guide incl. Oracle Cloud alternative and EC2 teardown: `DEPLOY.md`.
