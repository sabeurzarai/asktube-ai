# AskTube AI - Demo Script

Presentation guide for the IronHack final project. Total time: ~8 minutes.

---

## 1. Two-Minute Overview (say this first)

> "AskTube AI turns YouTube videos into interactive learning sessions.
> You search for a video, the app extracts its transcript, embeds it into a vector store,
> and then you chat with the content - getting transcript-grounded answers with clickable
> timestamp citations. Nothing is invented. Every answer is sourced from the video."

**Three things that make it interesting:**

1. **Full RAG pipeline** - not just an LLM wrapper. Retrieval, chunking, embeddings, and vector search all run on real YouTube data.
2. **LangChain agent orchestration** - the chat endpoint uses a tool-calling agent that decides whether to search YouTube, ingest a new video, or answer directly.
3. **Transcript-only contract** - the system prompt, the retrieval chain, and the evaluation metrics all enforce that the model cannot fabricate content outside the transcript.

---

## 2. Architecture (30 seconds, point at the screen)

```
Browser (Next.js 14)
    |
    +-- GET  /api/search                    YouTube Data API v3
    +-- GET  /api/videos/{id}/transcript    youtube-transcript-api + Whisper fallback
    +-- WS   /api/videos/{id}/ingest/stream real-time ingest progress events
    +-- POST /api/chat                      direct RAG (LangChain + ChatOpenAI)
    +-- WS   /api/chat/stream               streaming token-by-token chat
    +-- POST /api/agent/chat                LangChain tool-calling agent
            +-- tool: search_youtube_videos
            +-- tool: ingest_video          (transcript + chunk + embed + store)
            +-- tool: retrieve_context
            +-- tool: answer_question  --> ChromaDB similarity search
                                            +-- ChatOpenAI gpt-4o-mini
```

**Data flow for a question:**
User question -> agent decides tools -> similarity search on ChromaDB -> top-5 chunks injected into prompt -> answer generated -> timestamp citations extracted -> returned to frontend.

---

## 3. Live Demo Steps

### Step 1 - Open the app
`http://localhost:3000`

Point out: cinematic dark UI, search bar, video carousel with demo cards.

### Step 2 - Search
Type: **`python tutorial for beginners`**
Hit **Find videos**.

Point out: real YouTube API results, channel names, durations, carousel navigation.

### Step 3 - Select a video
Center the **Programming with Mosh** card. Click **Prepare down**.

Point out: processing screen shows **real backend steps** arriving over WebSocket - "Extracting transcript", "Creating semantic chunks", "Generating embeddings", "Indexing vector store" - with real percentage milestones, not a fake timer.

### Step 4 - Ask a question
In the AI Workspace, type: **`What is Python used for?`**

Point out:
- Grounded answer citing data science, ML, web development, automation with timestamp chips like `[00:02-01:02]`
- Small breadcrumb beneath the answer - `✦ ingest_video -> answer_question` - shows which agent tools fired
- **Read aloud** button appears on the response - click it to trigger browser TTS (SpeechSynthesis API, reads in a male voice: Microsoft David/Mark or Google UK English Male)

### Step 5 - Ask a follow-up
Type: **`How does Python handle type conversion?`**

Point out: the agent skips `ingest_video` (already done) and goes straight to `answer_question`. The breadcrumb shows only `answer_question`. Conversational memory is working.

### Step 6 - Test hallucination prevention
Type: **`What does the video say about React.js?`**

Expected response: "I cannot answer from the transcript" - the model correctly refuses rather than fabricating content.

### Step 7 - Show the evaluation runner (optional, 30 seconds)
```bash
cd backend
python scripts/run_evaluation.py
```

Point out: 17 eval cases across 6 categories - answerable questions, refusals, citation accuracy, summaries, hallucination prevention, and multi-turn memory. All run through `LangSmithEvaluationService`. Results: 5 PASS, 12 WARN, 0 FAIL (WARNs are the heuristic scorer being conservative about paraphrased answers - no behavioral failures). The backend also ships 82 pytest tests covering all routes, services, tools, and the new speech transcription endpoint.

---

## 4. Mandatory Requirements Coverage

| Requirement | How it is met |
|---|---|
| **LLM usage** | `ChatOpenAI` (gpt-4o-mini) in `RAGService` and `AgentService` |
| **Tool use** | 7 `StructuredTool` objects in `backend/app/tools/` - LangChain `bind_tools()` loop in `AgentService` |
| **RAG pipeline** | `ChromaVectorStoreService` (ChromaDB) + `OpenAIEmbeddings` + `ChatPromptTemplate` in `rag_service.py` |
| **LangChain agent** | `AgentService` - manual tool-calling loop, up to 8 iterations, grounded answer preservation |
| **YouTube data** | `YouTubeService` (Data API v3) + `TranscriptService` (youtube-transcript-api + Whisper fallback) |
| **API** | FastAPI with 13 endpoints across search, transcripts, chunking, vectorstore, chat, agent, evaluations |
| **Automated tests** | 82 pytest tests - tools, services, routes, WebSocket streams, evaluation metrics, speech transcription |
| **Frontend** | Next.js 14 / React / TypeScript / Tailwind CSS |
| **Evaluation** | `LangSmithEvaluationService` - groundedness, hallucination risk, citation quality, latency; 17-case eval dataset |

---

## 5. Optional Enhancements (built but not required)

- Voice search (Web Speech API - microphone + waveform animation)
- Whisper voice search fallback (`POST /api/speech/transcribe`) - when Web Speech API returns a network error, user taps mic again to record via MediaRecorder; audio is sent to the backend and transcribed with OpenAI Whisper
- WebSocket streaming chat (`/api/chat/stream`)
- WebSocket real-time ingest progress (`/api/videos/{id}/ingest/stream`)
- Text-to-speech on AI responses (browser SpeechSynthesis, opt-in, per-message, male voice preferred)
- Whisper transcription fallback for videos without captions
- LangSmith tracing integration (`@traceable` on all chain methods)
- Cinematic 3D AI assistant scene (Three.js / React Three Fiber)
- Framer Motion animations throughout
- `POST /api/evaluations/rag` and `POST /api/evaluations/conversation` endpoints
- 17-case evaluation dataset + CLI runner (`scripts/run_evaluation.py`)
- Mic diagnostic page (`/mic-test.html`) - tests capabilities, AudioContext level meter, MediaRecorder, Whisper API round-trip, and Web Speech API

---

## 6. YouTube Data Safety

Three things to say if asked:

1. **No audio or video is stored or served.** The primary flow reads publicly available caption text only - the same data a browser loads when you enable subtitles. No download happens.

2. **Whisper fallback is download-only for transcription.** Audio is downloaded to a local temp directory, transcribed with OpenAI Whisper, then the audio file is discarded. Audio files are gitignored and never committed.

3. **Only public videos are accessible.** `youtube-transcript-api` and `yt-dlp` only work on publicly accessible content. Private or members-only videos return an error.

Full details: `docs/youtube_data_strategy.md`.

---

## 7. Known Limitations

| Limitation | Reason |
|---|---|
| Transcript quality depends on YouTube captions | Auto-generated captions can have errors; Whisper fallback helps but adds latency (~30-60s per video) |
| Conversation memory is in-process only | `ConversationMemoryService` uses a Python dict - restarts wipe sessions |
| ChromaDB in persistent-file mode | Works locally; production would use HTTP client mode or a hosted vector DB |
| Agent does not stream | `POST /api/agent/chat` returns a full response; streaming uses the separate `/api/chat/stream` WebSocket |
| No authentication | The demo has no login or rate limiting - fine for a school project, not for production |
| Heuristic evaluator is conservative | Term-overlap groundedness scorer flags paraphrased answers as warnings; LLM evaluator mode would score correctly but costs extra API calls |
| Voice search requires closed Zoom on Windows | Zoom (and other conferencing apps) may claim exclusive mode on the microphone, causing MediaRecorder to capture 0-level audio. Fix: close Zoom, or disable exclusive mode in Windows Sound settings -> Properties -> Advanced |

---

## 8. Future Improvements

- Persistent session memory (Redis or database-backed)
- Streaming agent responses
- Multi-video cross-video search and comparison
- User accounts and saved sessions
- Chapter-level transcript segmentation using YouTube chapter metadata
- LangSmith evaluation dashboard with trend charts
- LLM-based evaluator mode (`RAG_EVALUATOR_MODE=llm`)
- Hosted deployment (Vercel + Railway / Fly.io)

---

## Quick Reference - Key Files

```
backend/
  app/services/rag_service.py              RAG chain (retrieve + generate)
  app/services/agent_service.py            LangChain tool-calling agent
  app/tools/                               7 StructuredTool wrappers
    search_youtube_videos.py
    extract_transcript.py
    chunk_transcript.py
    store_video_vectors.py
    ingest_video.py                        combined extract+chunk+store
    retrieve_context.py
    answer_question.py
  app/api/routes/vectorstore.py            ingest REST + WS stream endpoints
  app/services/observability_service.py    LangSmith evaluation metrics
  tests/fixtures/rag_eval_cases.json       17 eval cases
  scripts/run_evaluation.py               Evaluation CLI runner

frontend/
  components/landing/cinematic-hero.tsx    Main page orchestration
  components/landing/processing-screen.tsx WebSocket ingest progress
  components/landing/ai-workspace.tsx      Chat workspace + TTS
  lib/api.ts                               All backend API calls + WS_BASE
```
