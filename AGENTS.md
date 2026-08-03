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
| Vector store | ChromaDB **embedded in the backend process** (`CHROMA_USE_HTTP=false`) |
| DNS | DuckDNS A record → Vercel IP (duckdns is PSL-listed, so Vercel treats it as apex) |

- **Push to `main` auto-deploys BOTH platforms.** A broken push takes down the live demo.
- Render root dir = `backend/`, Docker runtime (ffmpeg included), `PORT=8000`.
- Vercel root dir = `frontend/`; `NEXT_PUBLIC_API_URL` is baked at build time —
  changing it requires a redeploy, not just saving the variable.
- Render free tier: sleeps after 15 idle min (30–60 s cold start); **no persistent
  disk** — ChromaDB + SQLite analytics reset on every restart. Warm `/health` and
  re-ingest a demo video before presenting.
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
  platform-specific — see that file) and a wiped + re-ingested ChromaDB.
- `CORS_ORIGINS` accepts JSON array, comma-separated, or single origin (the field
  uses `NoDecode` — do not remove it, plain values crash startup otherwise).
- Vector store switch: `VECTOR_BACKEND=chroma|pgvector|memory` — factory in
  `backend/app/services/vector_store/factory.py`. Unset defaults to `chroma` while
  ChromaDB still exists; Phase 2b-ii changes that to derive from `DATABASE_URL`.
  `VectorStoreService` in `vectorstore_service.py` owns embedding generation and
  delegates persistence to the selected store. Re-ingesting a video now REPLACES its
  chunks rather than upserting, so a chunking-parameter change no longer leaves stale
  chunks behind.
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

## Testing (verify before claiming done)

- Backend: `cd backend && python -m pytest` → expect **157 passed, 1 skipped** with
  local-embedding extras installed, or **153 passed, 5 skipped** without them
  (the extra 4 skips = local-embedding tests without extras; the remaining 1 skip
  present either way is the Alembic migration test, which skips unless
  `TEST_DATABASE_URL` is set). Set `OPENAI_API_KEY` to any dummy value first or
  9 speech tests fail with 503.
- Frontend: `cd frontend && npx tsc --noEmit && npm test` → expect **79 passed**.
- Frontend voice tests stub `@/lib/api` wholesale with `vi.mock` — `lib/analytics.ts`
  must NOT import from `lib/api.ts` (duplicate the resolver logic, keep in sync).

## History (short)

Originally deployed on EC2 (terminated July 2026, Elastic IP released). The repo
previously lived at a deeply nested Windows path — moved here 2026-07-05. Full
deployment guide incl. Oracle Cloud alternative and EC2 teardown: `DEPLOY.md`.
