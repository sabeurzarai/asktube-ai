# YouTube Data Strategy

This document explains how AskTube AI retrieves YouTube content, why it is designed this way, and how to adjust or restrict that behaviour.

---

## Primary Method: youtube-transcript-api

All transcript extraction starts with [`youtube-transcript-api`](https://pypi.org/project/youtube-transcript-api/), a Python library that fetches publicly available captions directly from YouTube's caption endpoint.

**How it works:**
1. The user submits a YouTube URL or video ID.
2. `transcript_service.py` calls `YouTubeTranscriptApi().list(video_id)` and fetches the caption track.
3. YouTube returns the caption track as a list of text segments with start-time metadata.
4. The segments are cleaned and passed to the chunking pipeline.

**No audio or video is downloaded in this flow.** The library reads the same caption data a browser would load when a user turns on subtitles - plain text delivered over HTTPS.

**No YouTube authentication is required.** Only publicly available captions are accessible. Private or members-only videos return an error and are not processed.

---

## Whisper Fallback (yt-dlp)

Some videos have no caption track - auto-generated or manual. For those cases, AskTube AI offers an optional Whisper-based fallback:

1. `yt-dlp` downloads the audio stream only (no video) for the target video.
2. The audio is passed to OpenAI Whisper (`whisper-1` API) for transcription.
3. The resulting text is used exactly like a caption-API transcript.

### Scope and safety

| Constraint | Detail |
|---|---|
| Triggered only when | `youtube-transcript-api` raises `TranscriptsDisabled` or `NoTranscriptFound` |
| What is downloaded | Audio stream only - no video pixels |
| Where files are stored | `AUDIO_CACHE_DIR` (default `data/audio_cache`) - local runtime only |
| Files committed to git | None - `data/`, `*.mp3`, `*.m4a`, `*.webm` are in `.gitignore` |
| Rate limiting | One video at a time; no bulk download loops |
| Authentication | None - only public videos are accessible |

### Disabling the Whisper fallback

Pass `use_whisper_fallback=false` in the query string:

```
GET /api/videos/{video_id}/transcript?use_whisper_fallback=false
```

When disabled, videos without captions return a `404` response explaining that no transcript is available.

---

## WebSocket Ingest Progress Stream

Video ingestion runs as a real-time WebSocket stream at:

```
WS /api/videos/{video_id}/ingest/stream
```

Events emitted during processing:

| Step | Label | Progress |
|---|---|---|
| `transcript` | Extracting transcript | 12% |
| `cleaning` | Cleaning timestamp segments | 30% |
| `chunking` | Creating semantic chunks | 45% |
| `embeddings` | Generating embeddings | 62% |
| `storing` | Indexing vector store | 85% |
| `memory` | Initializing AI memory | 93% |
| `ready` | Ready | 100% |
| `error` | Processing failed | 0% |

If the WebSocket connection fails, the frontend falls back to the REST endpoint (`POST /api/videos/{id}/ingest`) with a cosmetic progress ticker.

---

## Cloud Deployment and Proxy Reality

YouTube often blocks transcript requests from AWS, GCP, Azure, and other cloud-provider IP ranges. This is an infrastructure limitation of unofficial transcript retrieval, not a FastAPI or LangChain failure.

AskTube AI supports two proxy modes:

| Mode | Environment variables | Notes |
|---|---|---|
| Exact proxy URL | `WEBSHARE_PROXY_URL` | Preferred when Webshare provides a working curl/python proxy URL. The backend passes this into `GenericProxyConfig`. |
| Webshare helper | `WEBSHARE_PROXY_USERNAME`, `WEBSHARE_PROXY_PASSWORD`, `WEBSHARE_PROXY_LOCATIONS` | Lets `youtube-transcript-api` construct a Webshare residential proxy config. |

For EC2 demos:

- Use EC2 to prove Docker deployment, backend health, search, and the hosted UI.
- Use local development for the most reliable full transcript/RAG demo if the proxy endpoint cannot tunnel HTTPS to YouTube.
- Test proxies outside the app first:

```bash
curl -v --proxy "http://USER:PASS@p.webshare.io:80" https://api.ipify.org
```

If this command fails, the proxy endpoint/account is the issue. Ask the proxy provider for a Rotating Residential HTTPS CONNECT endpoint.

---

## No Copyrighted Media in the Repository

The following policy applies unconditionally:

- Audio files, video files, and raw transcript text are **never committed** to the Git repository.
- `.gitignore` excludes `*.mp3`, `*.m4a`, `*.webm`, `*.wav`, `data/`, and `audio_cache/`.
- ChromaDB vector data (embeddings) is stored in a local runtime directory (`backend/chroma_data/`). The SQLite index is committed for convenience in development; production deployments should use an external vector DB.
- Test fixtures use short, synthetically generated transcript snippets - not real YouTube content.

---

## Rate-Limit Guidelines

To remain a responsible API consumer:

- `youtube-transcript-api` calls are made once per video per session; results are cached in ChromaDB so repeat questions about the same video do not re-fetch.
- `yt-dlp` is used for one video at a time. No bulk scraping loops exist in the codebase.
- The YouTube Data API v3 (used only for video search and metadata) is called with the official API key and subject to Google's standard quota (10,000 units/day on a free project).
- OpenAI API calls (embeddings, chat, Whisper) are subject to the account's rate and cost limits.

---

## Academic-Use Positioning

AskTube AI is an educational tool built to demonstrate RAG architecture, LangChain agent orchestration, and conversational AI over long-form content.

- It does not redistribute YouTube content.
- It does not store or serve audio or video to end users.
- Transcripts are used solely as retrieval context for answering user questions about a video the user has already chosen to watch.
- The project is not intended for commercial deployment without a full legal and licensing review.

This positioning aligns with fair-use principles for research and education. Users deploying AskTube AI outside an academic context should review YouTube's [Terms of Service](https://www.youtube.com/t/terms) and the robots.txt restrictions before operating at scale.
