# AskTube AI

AI-powered YouTube learning platform. Search for videos, extract transcripts, and chat with the content using RAG (Retrieval-Augmented Generation) with timestamped citations.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, TypeScript, TailwindCSS, Framer Motion, Three.js |
| Backend | FastAPI, Python 3.12, LangChain, ChromaDB |
| AI | OpenAI GPT-4o-mini, text-embedding-3-small, Whisper |
| Observability | LangSmith (optional tracing) |
| Data | YouTube Data API v3, youtube-transcript-api 1.2.4 |
| Infra | Docker, Docker Compose, AWS EC2, optional Render |

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

## Deploying to AWS EC2

The current hosted demo runs the three Docker services on a single EC2 instance:

| Service | Public access |
|---------|---------------|
| Frontend | `http://<EC2_PUBLIC_IP>:3001` |
| Backend | `http://<EC2_PUBLIC_IP>:8000` |
| ChromaDB | internal Docker service, optionally exposed on `8001` for debugging |

**Live demo:** http://18.157.233.122:3001/

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
NEXT_PUBLIC_API_URL=http://<EC2_PUBLIC_IP>:8000
NEXT_PUBLIC_WS_URL=ws://<EC2_PUBLIC_IP>:8000
CORS_ORIGINS=http://<EC2_PUBLIC_IP>:3001,http://localhost:3000
```

If port `3000` is already occupied, map the frontend as `3001:3000` in `docker-compose.yml` and open port `3001` in the EC2 security group.

> Note: YouTube blocks transcript extraction from AWS/cloud IPs. The project includes Webshare residential proxy support. Set `WEBSHARE_PROXY_URL=http://<user>:<pass>@p.webshare.io:80` in your `.env` to route transcript requests through the proxy. This is required for production EC2 deployments.

---

## Deploying to Render

Render runs each service as a separate Docker container. You need three services:

1. **ChromaDB** - vector store with a persistent disk
2. **Backend** - FastAPI API
3. **Frontend** - Next.js app

### Step 1 - Deploy ChromaDB

1. Create a new **Web Service** on Render
2. Select **Deploy an existing image** -> `chromadb/chroma:1.3.7`
3. Set **Port**: `8000`
4. Add a **Disk** (Render Disks):
   - Mount path: `/chroma/chroma`
   - Size: 1 GB minimum
5. Add **Environment Variables**:
   ```
   IS_PERSISTENT=TRUE
   PERSIST_DIRECTORY=/chroma/chroma
   ANONYMIZED_TELEMETRY=FALSE
   ```
6. Copy the **internal service URL** (e.g. `asktube-chromadb` for internal hostname)

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
   CHROMA_USE_HTTP=true
   CHROMA_HOST=<chromadb-internal-hostname>
   CHROMA_PORT=8000
   CHROMA_COLLECTION_NAME=asktube_videos
   CORS_ORIGINS=https://<your-frontend>.onrender.com
   WHISPER_MODEL=whisper-1
   CHAT_MODEL=gpt-4o-mini
   EMBEDDING_MODEL=text-embedding-3-small
   CHUNK_MAX_CHARS=1200
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
| `CHROMA_USE_HTTP` | Docker/prod | `true` to use HTTP client |
| `CHROMA_HOST` | Docker/prod | ChromaDB hostname |
| `CHROMA_PORT` | Docker/prod | ChromaDB port (usually `8000`) |
| `CHROMA_PERSIST_DIR` | Local only | Path for embedded ChromaDB (default `./chroma_data`) |
| `CHAT_MODEL` | No | Default: `gpt-4o-mini` |
| `EMBEDDING_MODEL` | No | Default: `text-embedding-3-small` |
| `WHISPER_MODEL` | No | Default: `whisper-1` |
| `LANGSMITH_TRACING` | No | `true` to enable LangSmith tracing |
| `LANGSMITH_API_KEY` | If tracing | LangSmith API key |

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
|   +-- public/
|   |   +-- mic-test.html         # Microphone diagnostics page (/mic-test.html)
|   +-- next.config.mjs
|   +-- Dockerfile                # Production multi-stage build
|
+-- backend/                      # FastAPI app
|   +-- app/
|   |   +-- api/routes/           # search, chat, transcripts, vectorstore,
|   |   |                         #   agent, speech, evaluations, ingest
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
|   |   +-- ...                   # 98 pytest tests total
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
| POST | `/api/vectorstore/transcripts` | Store transcript chunks in ChromaDB |
| POST | `/api/chat` | RAG chat (single turn) |
| WS | `/api/chat/stream` | RAG chat with streaming response |
| POST | `/api/agent/chat` | LangChain tool-calling agent chat |
| POST | `/api/speech/transcribe` | Transcribe audio via Whisper (voice search fallback) |
| POST | `/api/evaluations/rag` | Run RAG quality evaluation |
| POST | `/api/evaluations/conversation` | Run conversation quality evaluation |

---

## Final Project Requirement Alignment

This section maps AskTube AI's implementation to the IronHack final-project grading criteria.

### Chatbot with LLM
The `/api/chat` endpoint accepts a user question and a YouTube video ID, retrieves relevant transcript chunks from ChromaDB via RAG, and generates a grounded answer using OpenAI GPT-4o-mini through LangChain's `ChatOpenAI`. Every answer includes timestamped citations so the user can verify the source.

### LangChain Tools / Tool-calling Agent
Seven `StructuredTool` objects live in `backend/app/tools/`: `search_youtube_videos`, `extract_transcript`, `chunk_transcript`, `store_video_vectors`, `ingest_video`, `retrieve_context`, and `answer_question`. `AgentService` (in `agent_service.py`) binds these tools to the LLM via `bind_tools()` and runs a tool-calling loop: the model decides which tools to call, the agent executes them, and the results are fed back until a final answer is produced. This is exposed through the dedicated `POST /api/agent/chat` route.

### Conversational Memory
`memory_service.py` (ConversationMemoryService) maintains per-session chat history keyed by `session_id`. The last *k* turns are injected into the prompt context on every request, enabling coherent multi-turn conversations about video content.

### ChromaDB Vector Database
`vectorstore_service.py` manages a ChromaDB collection (`asktube_videos`). Transcript chunks are embedded with `text-embedding-3-small` and upserted with metadata (video ID, title, timestamp). At query time, a similarity search retrieves the top-k most relevant chunks, which are passed to the LLM as grounding context.

### User Interface
The frontend is a Next.js 14 app with a cinematic, dark-mode UI (TailwindCSS, Framer Motion, Three.js). It provides a video search console, a chat panel with real-time streaming responses, a Three.js 3D robot assistant, and a floating journey companion - all with TTS read-aloud using a male voice.

**Why Next.js instead of Gradio or Streamlit?**
Gradio and Streamlit are designed for rapid ML demos. AskTube AI targets a production-quality user experience - server-side rendering, API route proxying, and complex animations are outside those frameworks' intended scope. Next.js 14 with the App Router delivers the performance and design flexibility required.

### Text Data Processing
`transcript_service.py` fetches captions via `youtube-transcript-api` and cleans the raw segments. `chunking_service.py` splits the cleaned text into overlapping chunks using LangChain's splitter, preserving timestamp metadata on each chunk. This pipeline converts raw YouTube captions into retrieval-ready documents.

### Testing and Evaluation
- **98 pytest tests** covering services, routes, tools, speech, WebSocket ingestion, and the agent pipeline.
- **Evaluation dataset**: `tests/fixtures/rag_eval_cases.json` - 17 hand-crafted RAG cases with expected answers and metadata.
- **CLI runner**: `scripts/run_evaluation.py` executes the evaluation dataset against the live backend and reports per-case scores.
- **Inline heuristic evaluation**: `RAG_EVALUATOR_MODE=heuristic` scores each RAG response at inference time (source coverage, answer length, hallucination-risk flag) and includes scores in the API response.
- **LangSmith tracing** (optional, `LANGSMITH_TRACING=true`) captures full chain traces for offline evaluation.

### Deployment
The project ships three Docker containers orchestrated via Docker Compose:
1. `chromadb` - ChromaDB vector store with a persistent disk volume
2. `backend` - FastAPI + LangChain application
3. `frontend` - Next.js production build

The project is deployed with Docker Compose on **AWS EC2** for the hosted demo and remains Render-compatible through the service-level Dockerfiles.

### YouTube Transcript API Usage
`youtube-transcript-api` (v1.2.4) is the **primary** and **preferred** method for extracting text from YouTube videos. It fetches publicly available auto-generated or manually uploaded captions without downloading any audio or video. See [YouTube Data Strategy](docs/youtube_data_strategy.md) for full details.

### Optional Voice Input
The frontend search console includes a microphone button that tries the browser's **Web Speech API** (`webkitSpeechRecognition`) first. If the Web Speech API fails with a network error, the frontend automatically falls back to recording audio via **MediaRecorder** and sending the file to `POST /api/speech/transcribe`, where OpenAI Whisper performs server-side transcription. A prompt of `"YouTube search query:"` guides the model, and responses shorter than 1 500 bytes are discarded as silence. A hallucination filter discards non-query outputs.

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

**"Unable to connect to ChromaDB"**
- Local dev: set `CHROMA_USE_HTTP=false` (uses embedded SQLite, no server needed)
- Docker / production: `CHROMA_USE_HTTP=true`, `CHROMA_HOST=chromadb`

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
