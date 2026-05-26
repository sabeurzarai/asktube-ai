# AskTube AI Manual Test Requirements

## Document Purpose

This document defines manual testing requirements for AskTube AI.

AskTube AI is a cinematic AI-powered YouTube learning platform combining:
- YouTube search (text + voice)
- Transcript extraction (youtube-transcript-api + Whisper fallback)
- Semantic chunking and ChromaDB vector storage
- LangChain RAG pipeline with ChatOpenAI
- LangChain tool-calling agent (`POST /api/agent/chat`)
- WebSocket real-time ingest progress stream
- Streaming AI chat over WebSocket
- Timestamped transcript citations
- Text-to-speech on AI answers (browser SpeechSynthesis)
- 3D AI assistant scene (Three.js)
- Cinematic Next.js 14 frontend

---

## Test Environments

| Environment | Requirement |
|---|---|
| Local frontend | `http://localhost:3000` |
| Local backend | `http://localhost:8000` |
| EC2 frontend | `http://<EC2_PUBLIC_IP>:3001` when port 3000 is occupied |
| EC2 backend | `http://<EC2_PUBLIC_IP>:8000` |
| API docs | `http://localhost:8000/docs` |
| Health check | `GET http://localhost:8000/health` -> `{"status":"ok"}` |
| Browser | Latest Chrome, Edge, or Firefox |
| Mobile emulation | Chrome DevTools at 390px width |

---

## Global Acceptance Criteria

The application passes manual acceptance when:
- A user can search for YouTube videos using text
- Voice search works where browser supports it
- Search results appear in the carousel
- A user can select a video and trigger ingestion
- Processing screen shows real backend step labels over WebSocket
- Chat workspace supports transcript-grounded questions
- AI answers include timestamp citations
- Agent tool breadcrumb shows which tools fired
- TTS read-aloud button works on AI answers
- Loading, empty, and error states are recoverable
- Interface is responsive without horizontal overflow

---

## Backend API Requirements

### API-001 Health Endpoint

```
GET /health
Expected: {"status": "ok", "service": "AskTube AI"}
```

### API-002 YouTube Search

```
GET /api/search?q=python+tutorial&max_results=5
Expected: {"query":..., "count":5, "videos":[...]}
Each video must include: video_id, title, channel_title, thumbnail_url, duration_seconds, youtube_url
```

Duration-filter variant:

```
GET /api/search?q=python+tutorial&max_results=5&duration_filter=under_10
Expected: all returned videos have duration_seconds < 600 when duration metadata is available
```

### API-003 Transcript Extraction

```
GET /api/videos/kqtD5dpn9C8/transcript?language=en&use_whisper_fallback=false
Expected: TranscriptResponse with segment_count > 0, source, full_text
```

### API-004 Video Ingest (REST)

```
POST /api/videos/kqtD5dpn9C8/ingest
Expected: {"video_id":..., "chunk_count":>0, "embedding_model":"text-embedding-3-small", "stored_chunk_ids":[...]}
```

### API-005 Video Ingest (WebSocket stream)

```
WS ws://localhost:8000/api/videos/kqtD5dpn9C8/ingest/stream
Expected event sequence:
  {"type":"step","step":"transcript","label":"Extracting transcript","progress":12}
  {"type":"step","step":"cleaning","label":"Cleaning timestamp segments","progress":30}
  {"type":"step","step":"chunking","label":"Creating semantic chunks","progress":45}
  {"type":"step","step":"embeddings","label":"Generating embeddings","progress":62}
  {"type":"step","step":"storing","label":"Indexing vector store","progress":85}
  {"type":"step","step":"memory","label":"Initializing AI memory","progress":93}
  {"type":"ready","progress":100,"chunk_count":>0}
Progress must increase monotonically. Final event type must be "ready" or "error".
```

### API-006 Direct RAG Chat

```
POST /api/chat
Body: {"message":"What is Python used for?","video_id":"kqtD5dpn9C8","top_k":5}
Expected: {"session_id":..., "answer":..., "citations":[...], "retrieved_context":[...]}
Answer must be grounded in transcript; citations must include timestamps.
```

### API-007 Streaming Chat (WebSocket)

```
WS ws://localhost:8000/api/chat/stream
Send: {"message":"Summarize the video","video_id":"kqtD5dpn9C8","top_k":5}
Expected events: ready -> context -> token (multiple) -> done
done event must include answer, citations, memory.
```

### API-008 Agent Chat

```
POST /api/agent/chat
Body: {"message":"What is Python used for?","video_id":"kqtD5dpn9C8"}
Expected: {"session_id":..., "answer":..., "citations":[...], "tool_steps_used":[...]}
tool_steps_used must list the tools called (e.g. ["ingest_video","answer_question"]).
On follow-up with session_id: tool_steps_used should contain only ["answer_question"].
```

### API-009 Transcript-Only Refusal

```
POST /api/agent/chat
Body: {"message":"What is the capital of France?","video_id":"kqtD5dpn9C8"}
Expected: answer contains "cannot answer" and "transcript"
citations must be empty or reflect that no relevant context was found.
```

### API-010 Conversational Memory

```
Turn 1: POST /api/agent/chat {"message":"What are tuples?","video_id":"kqtD5dpn9C8"}
Turn 2: POST /api/agent/chat {"message":"How are they different from lists?","session_id":<from turn 1>,"video_id":"kqtD5dpn9C8"}
Turn 2 must use session_id from turn 1.
Turn 2 answer should reference immutability (context from turn 1 memory).
```

### API-012 Speech Transcription

```
POST /api/speech/transcribe  (multipart/form-data, field: audio)
Expected: {"transcript": "..."}
Test: record an audio blob in the browser (MediaRecorder), POST it to this endpoint, verify the response contains a non-empty transcript string.
Edge cases:
  - Tiny file (<1500 bytes) -> {"transcript": ""} (minimum size not met)
  - Missing file field     -> 422 Unprocessable Entity
  - Backend unavailable    -> 503 Service Unavailable
Prompt sent to Whisper: "YouTube search query:"
Hallucination filter: single-word responses such as "you" or "thank you" are suppressed (returned as "").
Requires: python-multipart==0.0.20 installed in the backend.
```

### API-011 Evaluation Endpoints

```
POST /api/evaluations/rag
Body: {"message":"What is Python used for?","video_id":"kqtD5dpn9C8","top_k":5}
Expected: run, metrics, citations, retrieved_context, memory
metrics must include: groundedness_score, hallucination_risk, citation_quality, latency_ms, passed

POST /api/evaluations/conversation
Body: {"video_id":"kqtD5dpn9C8","top_k":5,"turns":[{"message":"What are tuples?"},{"message":"How do they differ from lists?"}]}
Expected: session_id, total_turns, average_latency_ms, average_groundedness_score, failed_turns, runs
```

---

## Frontend Requirements

### FR-001 Page Loads

- `http://localhost:3000` opens without error
- Brand name "AskTube AI" visible
- Search input visible
- Dark cinematic styling applied

### FR-002 Text Search

- Type a query and press Enter or click "Find videos"
- Loading state appears with progress bar
- Results appear in the video carousel
- Empty input shows empty state with guidance
- Search failure shows error state with retry

### FR-003 Voice Search

- Microphone button visible
- Clicking starts listening (pulse animation, waveform)
- Live transcript appears in input
- Clicking again stops listening
- Unsupported browser shows graceful message
- Microphone permission denied shows error message
- **Whisper fallback path**: if Web Speech API returns a network error, a second mic tap starts a MediaRecorder recording (requires an explicit user gesture); a live timer is shown; recording must be at least 1.5 seconds; the audio blob is POSTed to `POST /api/speech/transcribe` and the returned transcript fills the search input
- Windows note: if microphone gives 0-level audio (e.g. Zoom has exclusive mode), close Zoom or disable exclusive mode in Windows Sound settings

### FR-004 Video Carousel

- Centered card is visually enlarged and highlighted
- Previous/next arrows work
- Dot navigation works
- Touch swipe works on mobile emulation
- Each card shows title, channel, duration, transcript badge
- "Prepare down" button selects the video

### FR-005 Processing Screen - Real WebSocket Progress

- After selecting a video, processing screen appears
- Step labels match real backend events: "Extracting transcript", "Creating semantic chunks", "Generating embeddings", "Indexing vector store" etc.
- Progress percentage increases as real steps complete
- "Ready" state appears with "Start chatting" button when done
- If WebSocket fails, falls back to REST + cosmetic progress

**Negative test:** Disconnect from internet mid-processing -> error state with retry button appears.

### FR-006 AI Workspace Chat

- Chat input accepts text
- Submit button and Enter key send the message
- Suggested prompt buttons ("Summarize the video", "Show key timestamps", "Make study notes") work
- AI answer appears with timestamp citation chips
- Agent tool breadcrumb appears below answer (e.g. `✦ ingest_video -> answer_question`)
- Loading progress bar shows while waiting for answer
- Error state with retry appears on failure

### FR-007 Text-to-Speech

- "Read aloud" button appears on every AI assistant message
- Clicking it reads the answer text aloud
- Button changes to "Stop" while speaking
- Clicking "Stop" cancels speech
- Button is disabled (grayed) while a different message is speaking
- No auto-play - TTS only starts on explicit click
- Button is hidden on browsers without SpeechSynthesis support

### FR-008 Transcript Citations Panel

- Right panel shows "Citations will appear here after you ask a question"
- After first answer, citation cards appear with timestamp and text snippet
- Each citation is a link to the YouTube video at that timestamp (`?t=N`)
- Citations collapse on mobile (toggle)

### FR-009 Hallucination Prevention

Test in chat: **"What does this Python tutorial say about React.js?"**
Expected: answer contains "cannot answer" and references transcript. No React.js content invented.

Test in chat: **"What is the weather in Tokyo today?"**
Expected: refusal. No fabricated weather data.

### FR-010 Responsiveness

At 390px width:
- No horizontal overflow
- Search input and button usable
- Carousel swipeable
- Workspace panels stack vertically
- Transcript panel collapses with toggle
- TTS button visible

### FR-011 Accessibility

- All icon-only buttons have `aria-label`
- Progress bars have `role="progressbar"` with `aria-valuenow`
- Status changes announced via `aria-live`
- Tab order follows visual flow
- Focus indicators visible on dark background
- Decorative 3D canvas hidden from screen readers (`aria-hidden`)

---

## Regression Checklist

Run before demo or submission:

- [ ] `GET /health` returns 200
- [ ] Text search returns results
- [ ] Empty search shows empty state
- [ ] Search error shows retry
- [ ] Carousel navigation (arrows, dots, swipe) works
- [ ] Video selection starts processing
- [ ] Processing screen shows real step labels (check Network tab -> WS frames)
- [ ] Processing screen shows error + retry on failure
- [ ] Agent chat returns answer with citations
- [ ] Tool breadcrumb shows `ingest_video -> answer_question` on first question
- [ ] Tool breadcrumb shows only `answer_question` on follow-up (same session_id)
- [ ] Hallucination refusal works (off-topic question)
- [ ] TTS "Read aloud" button appears and works
- [ ] TTS "Stop" button cancels speech
- [ ] Citations panel shows timestamp cards with YouTube deep-links
- [ ] Transcript panel toggles on mobile
- [ ] No horizontal overflow at 390px
- [ ] Keyboard navigation works throughout
- [ ] Backend tests: `cd backend && python -m pytest -q` -> 98 pass
- [ ] Voice search Whisper fallback: trigger Web Speech API network error, tap mic a second time, record >1.5s, verify transcript fills the search box
- [ ] Mic exclusive mode (Windows): if microphone captures silence (0-level), close Zoom and re-test before reporting a bug

---

## Automated Test Summary

98 pytest tests:

| Test file | Count | Covers |
|---|---|---|
| `test_agent_route.py` | 7 | Agent chat route validation |
| `test_agent_service.py` | 14 | Agent tool dispatch, memory, citations |
| `test_tools.py` | 21 | All 7 LangChain tools |
| `test_ingest_stream.py` | 5 | WebSocket ingest stream events |
| `test_memory_service.py` | 12 | Session memory, history limits, and reset behavior |
| `test_chat_route.py` | 3 | REST + WebSocket streaming chat |
| `test_rag_service.py` | 4 | RAG utilities (timestamps, citations, memory) |
| `test_chunking_service.py` | 2 | Semantic chunking |
| `test_chunking_route.py` | 1 | Chunking route |
| `test_transcript_route.py` | 1 | Transcript extraction route |
| `test_transcript_service.py` | 6 | Transcript normalization and proxy configuration |
| `test_vectorstore_route.py` | 1 | Vectorstore route |
| `test_vectorstore_service.py` | 2 | ChromaDB helpers |
| `test_observability_service.py` | 4 | Evaluation metrics |
| `test_youtube_service.py` | 3 | YouTube utilities and duration filtering |
| `test_search_route.py` | 1 | Search route (pre-existing failure: expects 503 when API key present) |
| `test_speech_route.py` | 11 | Whisper transcription endpoint: transcript return, whitespace stripping, hallucination filter, 1500-byte minimum, 503/502/422 errors, prompt parameter |
