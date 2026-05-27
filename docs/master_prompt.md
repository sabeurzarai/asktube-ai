# AskTube AI - Project Specification

## Project Identity

AskTube AI is a cinematic AI-powered YouTube learning platform.

The product goal is to help users learn from YouTube videos through:
- AI-powered search
- conversational interaction
- transcript understanding
- semantic retrieval
- timestamped answers
- immersive cinematic UX

The platform feels like: Netflix + Perplexity AI + YouTube + futuristic AI assistant.

---

## As Built (current implementation)

### API Routes (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/search` | YouTube video search (Data API v3) |
| GET | `/api/videos/{id}/transcript` | Extract transcript (youtube-transcript-api + Whisper fallback) |
| GET | `/api/videos/{id}/chunks` | Get transcript chunks |
| POST | `/api/transcripts/chunks` | Chunk a transcript payload |
| POST | `/api/videos/{id}/ingest` | Ingest video (transcript + chunk + embed + store) |
| WS | `/api/videos/{id}/ingest/stream` | Real-time ingest progress over WebSocket |
| GET | `/api/vectorstore/search` | Semantic search in ChromaDB |
| POST | `/api/vectorstore/transcripts` | Ingest from a transcript payload |
| POST | `/api/chat` | Direct RAG chat |
| WS | `/api/chat/stream` | Streaming token-by-token RAG chat |
| POST | `/api/agent/chat` | LangChain tool-calling agent |
| POST | `/api/evaluations/rag` | Single-turn RAG evaluation |
| POST | `/api/evaluations/conversation` | Multi-turn conversation evaluation |
| POST | `/api/speech/transcribe` | Transcribe audio blob via OpenAI Whisper (multipart/form-data, field: audio; returns `{"transcript":"..."}`) |
| POST | `/api/analytics/events` | Capture frontend product/UX analytics events |
| GET | `/api/analytics/dashboard` | Return aggregated analytics dashboard data |
| GET | `/metrics` | Prometheus-format operational metrics |
| GET | `/health` | Health check |

### LangChain Tools (`backend/app/tools/`)

| Tool | Wraps |
|---|---|
| `search_youtube_videos` | `YouTubeService.search_videos()` |
| `extract_transcript` | `TranscriptService.get_transcript()` |
| `chunk_transcript` | `ChunkingService.chunk_transcript()` |
| `store_video_vectors` | `ChromaVectorStoreService.upsert_chunks()` |
| `ingest_video` | transcript + chunk + store pipeline (agent-optimised) |
| `retrieve_context` | `ChromaVectorStoreService.similarity_search()` |
| `answer_question` | `RAGService.answer()` |

### Services (`backend/app/services/`)

| Service | Responsibility |
|---|---|
| `YouTubeService` | YouTube Data API v3 search and metadata |
| `TranscriptService` | youtube-transcript-api + OpenAI Whisper fallback |
| `ChunkingService` | Semantic chunking with LangChain TextSplitter |
| `ChromaVectorStoreService` | ChromaDB upsert and cosine similarity search |
| `RAGService` | LangChain RAG chain with ChatPromptTemplate |
| `AgentService` | Tool-calling agent loop (ChatOpenAI.bind_tools) |
| `ConversationMemoryService` | In-process session memory (deque) |
| `LangSmithEvaluationService` | Heuristic groundedness + hallucination metrics |

### Analytics and Observability (`backend/app/analytics/`)

| Module | Responsibility |
|---|---|
| `models.py` | SQLAlchemy tables for analytics events, video metrics, chat metrics, and RAG metrics |
| `service.py` | Safe async tracking and dashboard aggregation |
| `middleware.py` | Automatic HTTP request latency, endpoint usage, and error status tracking |
| `prometheus.py` | Prometheus counters, gauges, and histograms |
| `database.py` | Async database engine/session and automatic table creation |

### Frontend (`frontend/`)

| Component | Purpose |
|---|---|
| `cinematic-hero.tsx` | Search, video selection, state orchestration |
| `search-console.tsx` | Text + voice search (Web Speech API) |
| `video-carousel.tsx` | Embla Carousel, Netflix-style scaling |
| `processing-screen.tsx` | WebSocket ingest progress with REST fallback |
| `ai-workspace.tsx` | Three-panel chat workspace + TTS |
| `floating-companion.tsx` | Animated journey state companion |
| `lib/api.ts` | All API + WebSocket calls |
| `lib/analytics.ts` | Product/UX event tracking with EC2-safe runtime API resolution |
| `app/analytics/page.tsx` | Observability dashboard with Recharts |

### Test Coverage

98 pytest tests across:
- agent route + service (21 tests)
- LangChain tools (21 tests)
- WebSocket ingest stream (5 tests)
- conversation memory service (12 tests)
- RAG service utilities (4 tests)
- chunking, transcript, vectorstore, and YouTube services (13 tests)
- route integration tests (8 tests)
- evaluation metrics (4 tests)
- speech transcription route - `test_speech_route.py` (11 tests): transcript return, whitespace stripping, hallucination filter, 1500-byte minimum, 503/502/422 errors, prompt parameter

---

## Technology Stack

### Frontend
- Next.js 14
- React 18
- TypeScript
- Tailwind CSS
- Framer Motion
- Embla Carousel
- Three.js + React Three Fiber + Drei
- lucide-react

### Backend
- FastAPI
- Python 3.12
- LangChain Core (`langchain-core`)
- LangChain OpenAI (`langchain-openai`)
- LangChain Text Splitters
- LangSmith
- SQLAlchemy async + aiosqlite / asyncpg
- Prometheus client
- ChromaDB
- OpenAI API (GPT-4o-mini, text-embedding-3-small, Whisper)
- youtube-transcript-api
- yt-dlp
- YouTube Data API v3

### Infrastructure
- Docker + Docker Compose
- ChromaDB persistent file mode (local) / HTTP client mode (production)

---

## Core Product Requirements (Implemented)

- Text-based YouTube search ✓
- Voice-based search (Web Speech API) ✓
- Horizontal cinematic video carousel ✓
- Video processing flow with real WebSocket progress ✓
- Transcript extraction (captions + Whisper fallback) ✓
- Semantic chunking ✓
- OpenAI embeddings generation ✓
- ChromaDB vector storage ✓
- LangChain RAG pipeline ✓
- LangChain tool-calling agent ✓
- Timestamped AI responses ✓
- Conversational memory ✓
- Streaming AI responses (WebSocket) ✓
- Text-to-speech on AI answers (browser SpeechSynthesis, male voice preferred) ✓
- Whisper voice search fallback (POST /api/speech/transcribe) ✓
- Mic diagnostic page (frontend/public/mic-test.html, served at /mic-test.html) ✓
- LangSmith tracing ✓
- RAG evaluation framework ✓
- 17-case evaluation dataset ✓
- 3D AI assistant scene (Three.js) ✓
- Cinematic animations (Framer Motion) ✓
- Responsive design ✓

---

## Global UI/UX Style

- Dark mode only
- Netflix-inspired cinematic aesthetic
- Glassmorphism panels
- Futuristic AI-native interface
- Smooth Framer Motion animations
- Soft neon glows (cyan, pink, emerald)
- Cinematic spacing and typography

### Colors
- Background: `#05070d` / `#0B0F19`
- Cards: `#111827` with `bg-white/[0.075]` glassmorphism
- Accent: cyan (`#22d3ee`), pink (`#ec4899`), emerald (`#34d399`)
- Text: white primary, `#94a3b8` (slate-400) secondary

### Typography
- Inter (primary)

---

## AI Response Rules

Responses must:
- use retrieved transcript context only
- refuse questions the transcript cannot answer
- include timestamp citations in `MM:SS` or `HH:MM:SS` format
- support conversational memory across turns
- never invent facts outside transcript content

---

## Evaluation

The heuristic evaluator (`LangSmithEvaluationService`) measures:
- `groundedness_score` - term overlap between answer and retrieved context
- `hallucination_risk` - composite risk score (0-1, lower is better)
- `citation_quality.score` - presence, timestamps, and context coverage
- `latency_ms` vs `LANGSMITH_LATENCY_BUDGET_MS`
- `passed` - true when all metrics within threshold

Run the evaluation CLI:
```bash
cd backend && python scripts/run_evaluation.py
```

---

## Analytics and Observability

The analytics system measures product usage, AI/RAG quality, ingestion pipeline performance, UX behaviour, and business-level activity.

Tracked examples:
- search submissions, search success, voice search, video selection, carousel movement
- processing started/completed/failed/retried
- chat starts, user messages, suggested prompts, transcript opens, timestamp clicks
- RAG retrieval latency, generation latency, retrieved chunks, citation coverage, token estimates
- transcript time, embedding time, vector insert/query time, chunk counts, Whisper fallback usage
- HTTP request latency, endpoint usage, WebSocket connections/failures, Prometheus metrics

Dashboard:
```text
GET /api/analytics/dashboard
Frontend page: /analytics
```

Prometheus:
```text
GET /metrics
GET /api/metrics
```

Storage defaults to SQLite for local/EC2 simplicity:
```dotenv
ANALYTICS_DATABASE_URL=sqlite+aiosqlite:///./data/analytics.db
```

Production can use PostgreSQL:
```dotenv
ANALYTICS_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/asktube_analytics
```

---

## YouTube Data Safety

- Primary method: `youtube-transcript-api` reads public caption text only - no download
- Whisper fallback: `yt-dlp` downloads audio-only stream, discarded after transcription
- No audio/video committed to git
- Only public videos accessible
- Full policy: `docs/youtube_data_strategy.md`
