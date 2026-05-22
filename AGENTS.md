# AskTube AI — Development Rules

## Tech Stack
- Next.js 14, TypeScript, TailwindCSS, Framer Motion, Three.js / React Three Fiber
- FastAPI (Python 3.12), LangChain, ChromaDB
- OpenAI GPT-4o-mini, text-embedding-3-small, Whisper
- LangSmith (optional tracing via `LANGSMITH_TRACING=true`)
- youtube-transcript-api 1.2.4, python-multipart 0.0.20
- Docker, Docker Compose, Render

## UI Rules
- Netflix-inspired cinematic UI — dark mode only
- Glassmorphism, smooth Framer Motion animations, premium micro-interactions
- Maintain consistent design system; do not introduce new component libraries without discussion

## Code Rules
- Modular architecture: one concern per file, clean reusable components
- TypeScript everywhere on the frontend; async endpoints on the backend
- Production-ready structure — no debug prints, no hardcoded secrets
- Run `pytest` from `backend/` before every commit; all 82 tests must pass
- Rebuild Docker containers after backend or frontend dependency changes: `docker compose up --build`

## AI / RAG Rules
- All chat answers must be grounded in retrieved transcript chunks — no free-form LLM hallucination
- Every answer must include timestamped citations so users can verify the source
- Use `RAG_EVALUATOR_MODE=heuristic` inline scoring; check `hallucination_risk` flag in the response
- **Agent tool-calling pattern**: add new capabilities as `StructuredTool` objects in `backend/app/tools/`,
  register them in `AgentService.bind_tools()`. Never call LLM services directly from route handlers.

## Voice Rules
- Voice search uses **Web Speech API first**; on network error display a message and switch to
  **MediaRecorder + POST /api/speech/transcribe** (Whisper) on the next mic click — do not skip the
  Web Speech attempt or hard-code the Whisper path
- Whisper prompt must be `"YouTube search query:"` to bias transcription toward search terms
- Discard responses shorter than 1 500 bytes (silence / noise) and responses that fail the
  hallucination filter before submitting as a search query

## TTS Rules
- Always select the male voice using the `voiceschanged` event on `speechSynthesis`, then filter
  `getVoices()` — never call `getVoices()` inline/synchronously, as voices are not loaded yet
- Apply the same male-voice selection pattern in cinematic-hero, ai-workspace, floating-companion,
  and ai-assistant-scene consistently
