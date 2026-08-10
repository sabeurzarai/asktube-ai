# AskTube AI

AI-powered YouTube learning platform. Search for videos, extract transcripts, and chat with the content using RAG (Retrieval-Augmented Generation) with timestamped citations.

**Demo video:** https://youtu.be/hSB3AvbUahY

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, TypeScript, TailwindCSS, Framer Motion, Three.js |
| Backend | FastAPI, Python 3.12, LangChain, langchain-community, SQLAlchemy async, Alembic |
| Vector store | PostgreSQL + pgvector (single `DATABASE_URL`, shared with analytics and conversation history) |
| AI | OpenAI GPT-4o-mini, text-embedding-3-small, Whisper |
| Observability | AskTube analytics dashboard, Prometheus metrics, LangSmith tracing |
| Data | YouTube Data API v3, youtube-transcript-api 1.2.4 |
| Infra | Docker, Docker Compose, Vercel (frontend), Render (backend), DuckDNS |

---

## Local Development (without Docker)

### Prerequisites
- Python 3.12+
- Node.js 18+
- ffmpeg (for Whisper fallback)

### 1. Clone and configure

```bash
git clone <repo>
cd "AskTube AI"
cp .env.example .env
# Fill in YOUTUBE_API_KEY and OPENAI_API_KEY in .env
```

### 2. Start the backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**. Backend API docs at **http://localhost:8000/docs**.

---

## Local Development (with Docker)

```bash
cp .env.example .env
# Fill in YOUTUBE_API_KEY and OPENAI_API_KEY

docker compose up --build
```

Open **http://localhost:3000**.

---

## Deploying to AWS EC2 (historical — no longer the live demo)

> **Superseded.** The EC2 instance was terminated in July 2026 and its Elastic IP
> released. The live demo now runs on Vercel + Render (see the next section), and
> the vector store is PostgreSQL + pgvector rather than a ChromaDB container.
> This section is kept because the Nginx/Let's Encrypt/compose layout is still a
> working recipe for a single-VM deployment — but it describes the old stack, and
> the ChromaDB service in it no longer exists in the codebase.

It ran the three Docker services on a single EC2 instance behind Nginx and HTTPS:

| Service | Public access |
|---------|---------------|
| Frontend | `https://asktube-ai.duckdns.org` |
| Backend API | `https://asktube-ai.duckdns.org/api/*` |
| Analytics dashboard | `https://asktube-ai.duckdns.org/analytics` |
| Prometheus metrics | `https://asktube-ai.duckdns.org/metrics` |
| ChromaDB | internal Docker service, optionally exposed on `8001` for debugging |

**Live demo:** https://asktube-ai.duckdns.org/

Quick deployment flow:

```bash
git clone https://github.com/sabeurzarai/asktube-ai.git
cd asktube-ai
cp .env.example .env
nano .env
docker-compose up -d --build
```

For EC2, set:

```dotenv
NEXT_PUBLIC_API_URL=https://asktube-ai.duckdns.org
NEXT_PUBLIC_WS_URL=wss://asktube-ai.duckdns.org
CORS_ORIGINS=https://asktube-ai.duckdns.org,http://localhost:3000
```

The public browser path goes through Nginx on ports `80` and `443`. Keep Docker ports `3001`, `8000`, and `8001` private to the instance unless you are temporarily debugging.

The production access layer is:

```text
Browser -> DuckDNS domain -> Let’s Encrypt HTTPS -> Nginx -> Next.js / FastAPI / ChromaDB
```

Voice search requires HTTPS in Chrome. The old raw-IP URL works for basic text testing, but microphone permission is blocked on insecure `http://` IP addresses.

> Note: YouTube blocks transcript extraction from datacenter IPs, so any hosted deployment needs the Webshare residential proxy: set `WEBSHARE_PROXY_URL=http://<user>:<pass>@p.webshare.io:80` in your `.env`. **Use a rotating username** (`<user>-rotate`, not a pinned `<user>-DE-1`) — a pinned username always leaves through the same exit IP, and when YouTube flags it, ingestion stops while the account and quota are perfectly healthy. Even rotating, roughly one attempt in six draws a flagged IP, so `TranscriptService` retries a blocked fetch up to three times when a proxy is configured.

---

## Deploying to Render

You need three pieces:

1. **PostgreSQL with pgvector** - the vector store, plus analytics and conversation history
2. **Backend** - FastAPI API on Render
3. **Frontend** - Next.js app (the live demo uses Vercel; Render works too)

### Step 1 - Provision PostgreSQL with pgvector

Any managed Postgres with the `pgvector` extension works. The live demo uses a
Supabase free-tier project.

1. Create the database and enable the extension: `create extension if not exists vector;`
2. Copy the connection string and change the scheme to `postgresql+asyncpg://`.
   Use the **port-5432** (direct/session) entry, not the project URL — the
   `https://<ref>.supabase.co` address shown in the dashboard is the REST
   endpoint, not the database.
3. Run the migrations once, against that port-5432 endpoint:
   ```bash
   cd backend && python -m alembic upgrade head
   ```
   Nothing runs them automatically at container start.

There is no separate vector-store service and no persistent disk to attach:
`DATABASE_URL` alone selects the pgvector backend. Leave `VECTOR_BACKEND` unset
and it is derived — set means `pgvector`, absent means an in-memory store that
is lost on restart.

### Step 2 - Deploy the Backend

1. Create a new **Web Service** on Render
2. Select **Docker** deployment from your Git repository
3. Set **Root Directory**: `backend`
4. Set **Dockerfile Path**: `Dockerfile`
5. Set **Port**: `8000`
6. Add **Environment Variables**:
   ```
   YOUTUBE_API_KEY=<your key>
   OPENAI_API_KEY=<your key>
   DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/postgres
   VECTOR_COLLECTION_NAME=asktube_videos
   CORS_ORIGINS=https://<your-frontend>.onrender.com
   WEBSHARE_PROXY_URL=http://<user>:<pass>@p.webshare.io:80
   WHISPER_MODEL=whisper-1
   CHAT_MODEL=gpt-4o-mini
   EMBEDDING_MODEL=text-embedding-3-small
   CHUNK_MAX_CHARS=600
   CHUNK_OVERLAP_SEGMENTS=1
   AUDIO_CACHE_DIR=/app/data/audio_cache
   RAG_EVALUATOR_MODE=heuristic
   HALLUCINATION_RISK_THRESHOLD=0.35
   ```
7. Copy the **service URL** (e.g. `https://asktube-backend.onrender.com`)

### Step 3 - Deploy the Frontend

1. Create a new **Web Service** on Render
2. Select **Docker** deployment from your Git repository
3. Set **Root Directory**: `frontend`
4. Set **Dockerfile Path**: `Dockerfile`
5. Set **Port**: `3000`
6. Add **Build-time Environment Variable** (Next.js bakes this in at build time):
   ```
   NEXT_PUBLIC_API_URL=https://<your-backend>.onrender.com
   ```
7. Add **Runtime Environment Variable**:
   ```
   NODE_ENV=production
   ```

### Step 4 - Verify

- Frontend: `https://<frontend>.onrender.com`
- Backend health: `https://<backend>.onrender.com/health`
- Backend docs: `https://<backend>.onrender.com/docs`

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `YOUTUBE_API_KEY` | Yes | Google Cloud -> YouTube Data API v3 |
| `OPENAI_API_KEY` | Yes | OpenAI - embeddings, chat, Whisper |
| `NEXT_PUBLIC_API_URL` | Yes (prod) | Backend URL used by the frontend |
| `CORS_ORIGINS` | Yes (prod) | Comma-separated frontend origins |
| `DATABASE_URL` | Yes (prod) | Single async SQLAlchemy URL (`postgresql+asyncpg://...`) for vectors, analytics and conversation history |
| `VECTOR_BACKEND` | No | `pgvector` or `memory`. Unset derives from `DATABASE_URL`: set → `pgvector`, absent → `memory` |
| `VECTOR_COLLECTION_NAME` | No | Default: `asktube_videos`. Reported as `collection_name` in API responses |
| `CONVERSATION_BACKEND` | No | `postgres` or `memory`. Same derivation as `VECTOR_BACKEND` |
| `CHAT_MODEL` | No | Default: `gpt-4o-mini` (used when `LLM_PROVIDER=openai`) |
| `EMBEDDING_MODEL` | No | Default: `text-embedding-3-small` (used when `EMBEDDING_PROVIDER=openai`) |
| `EMBEDDING_PROVIDER` | No | `openai` (default) or `local` — free CPU embeddings via HuggingFace |
| `LOCAL_EMBEDDING_MODEL` | No | Default: `sentence-transformers/all-MiniLM-L6-v2` |
| `WHISPER_MODEL` | No | Default: `whisper-1` |
| `LLM_PROVIDER` | No | `openai` (default) or `nvidia` — chat generation only |
| `NVIDIA_API_KEY` | If `LLM_PROVIDER=nvidia` | Key from https://build.nvidia.com |
| `NVIDIA_BASE_URL` | No | Default: `https://integrate.api.nvidia.com/v1` |
| `NVIDIA_CHAT_MODEL` | No | Default: `moonshotai/kimi-k2.6` |
| `NVIDIA_TOOL_CALLING` | No | Default: `true`. Set `false` to make the agent fall back to plain RAG |
| `LANGSMITH_TRACING` | No | `true` to enable LangSmith tracing |
| `LANGSMITH_API_KEY` | If tracing | LangSmith API key |
| `ANALYTICS_ENABLED` | No | Enable product, RAG, pipeline, UX, and business analytics |
| `ANALYTICS_DATABASE_URL` | No | Async SQLAlchemy URL for analytics storage; SQLite by default, PostgreSQL supported |
| `PROMETHEUS_ENABLED` | No | Exposes Prometheus-compatible metrics at `/metrics` |

---

## Health Check

```bash
curl https://<backend>.onrender.com/health
# {"status":"ok","service":"AskTube AI"}
```

---

## Project Structure

```
AskTube AI/
+-- frontend/                     # Next.js 14 app
|   +-- app/
|   |   +-- analytics/            # Production analytics dashboard
|   +-- components/
|   |   +-- landing/              # Page sections
|   |   |   +-- cinematic-hero.tsx
|   |   |   +-- search-console.tsx
|   |   |   +-- video-carousel.tsx
|   |   |   +-- processing-screen.tsx
|   |   |   +-- ai-workspace.tsx
|   |   |   +-- ai-assistant-scene.tsx
|   |   |   +-- about-section.tsx
|   |   +-- floating-companion.tsx
|   +-- lib/api.ts                # Backend API client
|   +-- lib/analytics.ts          # Frontend product/UX event tracking
|   +-- public/
|   |   +-- mic-test.html         # Microphone diagnostics page (/mic-test.html)
|   +-- next.config.mjs
|   +-- Dockerfile                # Production multi-stage build
|
+-- backend/                      # FastAPI app
|   +-- app/
|   |   +-- analytics/            # SQLAlchemy models, service, middleware, Prometheus
|   |   +-- api/routes/           # search, chat, transcripts, vectorstore,
|   |   |                         #   agent, speech, evaluations, ingest, analytics
|   |   +-- services/             # youtube, transcript, chunking, RAG,
|   |   |                         #   vectorstore, agent, memory, evaluation
|   |   |   +-- agent_service.py  # LangChain tool-calling agent (bind_tools loop)
|   |   +-- tools/                # 7 LangChain StructuredTool objects
|   |   |   +-- search_youtube_videos.py
|   |   |   +-- extract_transcript.py
|   |   |   +-- chunk_transcript.py
|   |   |   +-- store_video_vectors.py
|   |   |   +-- ingest_video.py
|   |   |   +-- retrieve_context.py
|   |   |   +-- answer_question.py
|   |   +-- core/config.py        # All settings via env vars
|   +-- scripts/
|   |   +-- run_evaluation.py     # CLI runner for RAG evaluation dataset
|   +-- tests/
|   |   +-- fixtures/
|   |   |   +-- rag_eval_cases.json  # 17 RAG evaluation cases
|   |   +-- ...                   # 306 pytest tests total
|   +-- requirements.txt
|   +-- Dockerfile                # Production build with ffmpeg
|
+-- docker-compose.yml            # Production compose (all 3 services)
+-- docker-compose.dev.yml        # Dev override (hot-reload volumes)
+-- .env.example                  # Template - copy to .env
+-- README.md
```

---

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/search` | Search YouTube videos |
| GET | `/api/videos/{id}/transcript` | Fetch transcript for a video |
| GET | `/api/videos/{id}/chunks` | Retrieve stored chunks for a video |
| POST | `/api/transcripts/chunks` | Chunk raw transcript text |
| POST | `/api/videos/{id}/ingest` | Ingest video (REST, with progress polling) |
| WS | `/api/videos/{id}/ingest/stream` | Ingest video with real-time WebSocket progress events |
| GET | `/api/vectorstore/search` | Semantic search over stored vectors |
| POST | `/api/vectorstore/transcripts` | Embed transcript chunks and store them in pgvector |
| POST | `/api/chat` | RAG chat (single turn) |
| WS | `/api/chat/stream` | RAG chat with streaming response |
| POST | `/api/agent/chat` | LangChain tool-calling agent chat |
| POST | `/api/speech/transcribe` | Transcribe audio via Whisper (voice search fallback) |
| POST | `/api/evaluations/rag` | Run RAG quality evaluation |
| POST | `/api/evaluations/conversation` | Run conversation quality evaluation |
| POST | `/api/analytics/events` | Capture frontend product/UX analytics events |
| GET | `/api/analytics/dashboard` | Return dashboard aggregates |
| GET | `/metrics` or `/api/metrics` | Prometheus metrics for HTTP, RAG, embeddings, vector search, processing, WebSockets |

---

## Final Project Requirement Alignment

This section maps AskTube AI's implementation to the IronHack final-project grading criteria.

### Chatbot with LLM
The `/api/chat` endpoint accepts a user question and a YouTube video ID, retrieves relevant transcript chunks from the pgvector store via RAG, and generates a grounded answer using OpenAI GPT-4o-mini through LangChain's `ChatOpenAI`. Every answer includes timestamped citations so the user can verify the source.

### Whole-video summaries for broad questions
A question like *"what is this video about?"* asks about the whole, not a passage, and top-k retrieval answers it badly by construction — it picks five chunks and hopes they represent ten minutes of video. Measured, this shows up as the weakest similarity score of any on-topic question.

Such questions therefore skip retrieval. `is_broad_question` recognises them with a **pure pattern match and no model call** — deliberately, because an LLM classifier would be non-deterministic, would add latency to every request, and would break the guarantee that a first turn costs no extra call. Phrasings nobody listed simply fall through to normal retrieval, which is the previous behaviour, so a miss is never a regression. English and German phrasings are both recognised.

`summarize_video` then reads *every* chunk of the video, rebuilds a timestamped transcript, and makes **one** model call. Timestamps in the answer are validated against the real chunks before becoming citations, so a mark the model invented is dropped rather than presented as a source. The whole path degrades rather than fails: no chunks, a transcript over 40,000 characters, or a failed model call each send the question back to ordinary retrieval.

### Which chat endpoint the frontend uses
Two chat surfaces exist and they do not share a route. The **AI workspace** (`components/landing/ai-workspace.tsx`) calls `POST /api/agent/chat`; only the floating companion (`components/floating-companion.tsx`) calls `POST /api/chat`. Both reach the same `RAGService` underneath, so the summarisation path and the query rewrite apply to either — but the agent wraps them in a tool-calling loop that can behave differently, which is why a chat change verified only against `/api/chat` has not been verified against what the demo actually uses.

### LangChain Tools / Tool-calling Agent
Seven `StructuredTool` factories live in `backend/app/tools/`, but `get_agent_service` binds only **four** of them to the model: `search_youtube_videos`, `ingest_video`, `retrieve_context` and `answer_question`. The other three — `extract_transcript`, `chunk_transcript` and `store_video_vectors` — are the individual steps that `ingest_video` already composes into one call, so exposing them separately would only give the model more ways to build the same pipeline by hand. `AgentService` (in `agent_service.py`) binds the four via `bind_tools()` and runs a tool-calling loop: the model decides which tools to call, the agent executes them, and the results are fed back until a final answer is produced. This is exposed through the dedicated `POST /api/agent/chat` route.

### Conversational Memory
`memory_service.py` resolves a `ConversationStore` — Postgres when `DATABASE_URL` is set, in-process otherwise — keyed by `session_id`. History is trimmed to the newest 8 messages per session and injected into the prompt context on every request, enabling coherent multi-turn conversations about video content. Memory degrades rather than fails: if the store is unreachable the answer is still produced, with empty history.

Follow-up questions are also **rewritten into standalone search queries** before retrieval. A question like *"and what did you just say it uses?"* carries no information about the video, so embedding it verbatim returns arbitrary chunks. The rewrite resolves it against the conversation; first turns are never rewritten, and generation always receives the original question.

### pgvector Vector Store
`vectorstore_service.py` owns embedding generation and delegates persistence to the store selected by `VECTOR_BACKEND` (`pgvector` or `memory`). Transcript chunks are embedded with `text-embedding-3-small` and written to the `transcript_chunks` table with metadata (video ID, timestamps, segment indices). At query time a cosine similarity search (`<=>`, HNSW index) retrieves the top-k most relevant chunks, which are passed to the LLM as grounding context. Re-ingesting a video **replaces** its chunks rather than upserting them.

### User Interface
The frontend is a Next.js 14 app with a cinematic, dark-mode UI (TailwindCSS, Framer Motion, Three.js). It provides a video search console, a chat panel with real-time streaming responses, a Three.js 3D robot assistant, and a floating journey companion - all with TTS read-aloud using a male voice.

**Why Next.js instead of Gradio or Streamlit?**
Gradio and Streamlit are designed for rapid ML demos. AskTube AI targets a production-quality user experience - server-side rendering, API route proxying, and complex animations are outside those frameworks' intended scope. Next.js 14 with the App Router delivers the performance and design flexibility required.

### Text Data Processing
`transcript_service.py` fetches captions via `youtube-transcript-api` and cleans the raw segments. `chunking_service.py` splits the cleaned text into overlapping chunks using LangChain's splitter, preserving timestamp metadata on each chunk. This pipeline converts raw YouTube captions into retrieval-ready documents.

### Testing and Evaluation
- **306 backend tests** (`cd backend && python -m pytest`) covering services, routes, tools, speech, WebSocket ingestion, retrieval quality and the agent pipeline, plus **79 frontend tests** (`cd frontend && npx tsc --noEmit && npm test`).
- **Answer-quality dataset**: `tests/fixtures/rag_eval_cases.json` - 15 hand-crafted RAG cases with expected answers and metadata. It scores ANSWERS: groundedness, citation quality, latency.
- **Retrieval dataset**: `tests/fixtures/retrieval_eval_cases.json` - 29 conversation cases across **two deliberately unrelated videos** (a Python tutorial and a biology lecture), scored on whether the expected passage reaches the top-k. It measures a different stage: in the failure that motivated it, the answer was faithfully grounded in the chunks it received - the wrong chunks had been retrieved, which no answer-quality score can see. `scripts/run_retrieval_eval.py --frozen` runs it deterministically; `tests/test_retrieval_eval_fixture.py` validates the fixture offline, with no database and no API key.
- **CLI runner**: `scripts/run_evaluation.py` executes the evaluation dataset against the live backend and reports per-case scores.
- **Inline heuristic evaluation**: `RAG_EVALUATOR_MODE=heuristic` scores each RAG response at inference time (source coverage, answer length, hallucination-risk flag) and includes scores in the API response.
- **LangSmith tracing** (optional, `LANGSMITH_TRACING=true`) captures full chain traces for offline evaluation.

### Analytics and Observability
AskTube AI includes a production-style analytics system. The frontend tracks product and UX events such as search submissions, video selections, carousel movement, voice search, processing state, chat messages, prompt clicks, transcript opens, timestamp clicks, and 3D assistant interactions. The backend records HTTP latency, search events, video processing metrics, embedding/vector timings, RAG latency, citation coverage, tool execution, chat metrics, and WebSocket failures.

Analytics are stored in SQLAlchemy tables (`analytics_events`, `video_metrics`, `chat_metrics`, `rag_metrics`) and displayed in the Next.js dashboard at `/analytics`. Every metric card and chart on the dashboard includes an inline tooltip explaining what the metric measures and why it matters. Prometheus-format operational metrics are exposed at `/metrics`. LangSmith remains available for chain and tool tracing. See [Analytics and Observability](docs/analytics_observability.md).

### Deployment
Local development ships three Docker containers orchestrated via Docker Compose:
1. `postgres` - `pgvector/pgvector:pg16`, the vector store
2. `backend` - FastAPI + LangChain application
3. `frontend` - Next.js production build

Migrations are a manual step, run once: `docker compose exec backend python -m alembic upgrade head`.

Persistence is driven by a single `DATABASE_URL`, which covers vectors, analytics and conversation history. Unset, everything falls back to SQLite and in-memory stores — fine locally, but a deployment that has a database and forgets the variable would silently run without persistence.

The hosted demo runs the frontend on **Vercel** and the backend on **Render** (both free tier, $0/month), with the database on managed Postgres. It is served at `https://asktube-ai.duckdns.org` via a DuckDNS A record pointing at Vercel, so browser microphone permissions work over HTTPS.

### YouTube Transcript API Usage
`youtube-transcript-api` (v1.2.4) is the **primary** and **preferred** method for extracting text from YouTube videos. It fetches publicly available auto-generated or manually uploaded captions without downloading any audio or video. See [YouTube Data Strategy](docs/youtube_data_strategy.md) for full details.

### Optional Voice Input
The frontend search console includes a microphone button that tries the browser's **Web Speech API** (`webkitSpeechRecognition`) first. If the Web Speech API fails with a network error, the frontend automatically falls back to recording audio via **MediaRecorder** and sending the file to `POST /api/speech/transcribe`, where OpenAI Whisper performs server-side transcription. A prompt of `"YouTube search query:"` guides the model, and responses shorter than 1 500 bytes are discarded as silence. A hallucination filter discards non-query outputs.

Browser microphone access requires a secure origin. Use `https://asktube-ai.duckdns.org` for the hosted demo or `http://localhost:3000` for local development; Chrome blocks microphone permission on plain `http://` public IP URLs.

---

### Optional: NVIDIA chat provider (NIM)

AskTube AI defaults to OpenAI for chat generation. You can optionally route **chat generation only** through NVIDIA's OpenAI-compatible NIM endpoint (`https://integrate.api.nvidia.com/v1`). This swaps the chat model while leaving embeddings and Whisper on OpenAI, so stored vectors and citations keep working unchanged.

1. Get a free key at **https://build.nvidia.com** (free endpoints are rate-limited — fine for demos, not production traffic).
2. In your `.env`, set:
   ```dotenv
   LLM_PROVIDER=nvidia
   NVIDIA_API_KEY=<your build.nvidia.com key>
   # Optional overrides (defaults shown):
   # NVIDIA_CHAT_MODEL=moonshotai/kimi-k2.6
   # NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
   ```
   `OPENAI_API_KEY` is **still required** (embeddings use `text-embedding-3-small`, Whisper uses `whisper-1`).
3. Restart the backend:
   ```bash
   docker compose up -d --build backend
   ```

**Model notes.** Any model on build.nvidia.com tagged "Tool Use" works. Recommended default: `moonshotai/kimi-k2.6`. Faster alternative: `deepseek-ai/deepseek-v4-flash`; newest flagship: `z-ai/glm-5.2`.

**Tool calling.** The agent relies on tool calling. If your chosen model's tool calling misbehaves, set `NVIDIA_TOOL_CALLING=false` — the agent then skips the tool pipeline and answers via the existing transcript-grounded RAG path (citations preserved, `tool_steps_used` empty). Set it back to `true` for the full agent.

To return to OpenAI, unset `LLM_PROVIDER` (or set `LLM_PROVIDER=openai`) and restart.

---

### Optional: Local embeddings (free, no API key)

By default AskTube AI uses OpenAI's `text-embedding-3-small` for embeddings (cheap, but not free). You can instead run a **HuggingFace `sentence-transformers` model on the CPU** — fully free, no API calls, no key. Combined with NVIDIA chat, this makes the entire inference path $0.

**Trade-offs:** the Docker image grows by ~800 MB (torch), and CPU embedding is slower than the OpenAI API (fine for demos). First ingest downloads the model (~80 MB) and caches it under `/app/data/hf_cache` (persists across restarts).

1. In your `.env`, set:
   ```dotenv
   EMBEDDING_PROVIDER=local
   # Optional (default shown):
   # LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
   ```
2. Rebuild the backend (first build downloads torch; expect ~10-20 min):
   ```bash
   docker compose up -d --build backend
   ```
3. ⚠️ **Wipe the stored vectors and re-ingest every video.** The embedding
   dimension changes 1536→384, and `transcript_chunks.embedding` is a
   fixed-width `vector(1536)` column — mixing dimensions returns garbage rather
   than failing:
   ```bash
   docker compose exec postgres psql -U postgres -c "truncate table transcript_chunks;"
   ```
   Changing the column width needs its own Alembic migration.
4. Re-ingest each video you want to query.

To return to OpenAI embeddings, set `EMBEDDING_PROVIDER=openai`, wipe the collection again, rebuild, and re-ingest.

---

### YouTube Copyright and Data Handling

AskTube AI is built for academic and educational use. Key commitments:

- **No full-video downloads in the normal flow.** The app reads publicly available caption data only.
- **yt-dlp is a Whisper fallback only.** When a video has no captions, `yt-dlp` may download a short audio segment for local Whisper transcription. This is disabled by default and can be turned off entirely (see [YouTube Data Strategy](docs/youtube_data_strategy.md)).
- **No copyrighted media is committed to this repository.** Transcripts, audio, and video files are generated at runtime and stored locally or in ephemeral containers only.

---

## Common Issues

**"YOUTUBE_API_KEY is not configured"**
Set `YOUTUBE_API_KEY` in your `.env` or Render environment variables.

**"Incorrect API key" (OpenAI 401)**
Your `OPENAI_API_KEY` is invalid or expired. Generate a new one at [platform.openai.com](https://platform.openai.com/api-keys).

**"NVIDIA_API_KEY is required when LLM_PROVIDER=nvidia"**
You set `LLM_PROVIDER=nvidia` but didn't provide `NVIDIA_API_KEY`. Get a free key at [build.nvidia.com](https://build.nvidia.com) and add it to `.env`, or switch back with `LLM_PROVIDER=openai`.

**Retrieval returns nothing, or `result_count: 0` with HTTP 200**
An empty `transcript_chunks` table looks like a broken query rather than missing
data. Check the row count before debugging retrieval. If the table is populated
but nothing comes back, confirm the backend actually selected pgvector: with
`VECTOR_BACKEND` unset it is derived from `DATABASE_URL`, so a missing
`DATABASE_URL` silently yields an in-memory store that is empty after restart.

**`NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:https`**
`DATABASE_URL` holds the Supabase *project* URL (the REST endpoint) instead of a
connection string. Use the port-5432 entry from Supabase → Connect with the
scheme changed to `postgresql+asyncpg://`.

**CORS errors in browser**
Add your frontend URL to `CORS_ORIGINS` in the backend:
```
CORS_ORIGINS=https://your-frontend.onrender.com
```

**YouTube thumbnails not loading**
Already configured in `next.config.mjs` - `i.ytimg.com` is in the allowed image domains.

**Videos have no transcript**
The Whisper fallback requires ffmpeg. In Docker it is installed automatically. Locally, install it via `winget install Gyan.FFmpeg` or from [ffmpeg.org](https://ffmpeg.org/download.html).

**Microphone records silence (Windows)**
Windows may grant exclusive microphone access to another application (e.g. Teams, Discord), blocking MediaRecorder. Fix:
1. Open **Sound Settings -> Input -> your microphone -> Properties**
2. Under the **Advanced** tab, uncheck **"Allow applications to take exclusive control of this device"**
3. Restart the browser.
Alternatively open `http://localhost:3000/mic-test.html` to verify the mic is working before using voice search.
