# AskTube AI Analytics and Observability

AskTube AI includes an analytics and observability layer for product usage, RAG quality, video processing, UX behaviour, and operational health.

---

## What Is Tracked

| Area | Examples |
|---|---|
| Product analytics | searches, selected videos, chat starts, suggested prompt usage, timestamp clicks |
| AI / RAG analytics | retrieval latency, generation latency, chunks retrieved, token estimates, citation coverage, hallucination warnings |
| Pipeline analytics | transcript time, embedding time, processing duration, chunk count, Whisper fallback usage |
| UX analytics | carousel scrolls, voice search success/failure, processing retry, 3D assistant interactions, TTS-related chat events |
| Business metrics | active users, sessions, videos processed, questions per day, return rate, average processing time |

Frontend events are sent from `frontend/lib/analytics.ts` to `POST /api/analytics/events`. Backend services also record metrics directly during search, ingestion, vector search, RAG answering, agent tool execution, and WebSocket streaming.

---

## Dashboard

The analytics dashboard is available at:

```text
/analytics
```

It reads from:

```text
GET /api/analytics/dashboard
```

Dashboard sections:

- Overview: daily active users, weekly active users, questions today, videos processed, average session and processing time, voice usage, search success rate
- AI metrics: RAG latency, token usage estimates, retrieved chunks, citation coverage
- Pipeline metrics: transcript extraction time, embedding duration, processing duration, chunk counts
- UX metrics: carousel click rate, voice failures, chat retention, timestamp clicks, 3D assistant engagement
- Business metrics: sessions, return rate, processed videos, questions per day, average processing time
- Recent events: the latest tracked product and system events

The dashboard is intentionally dark, cinematic, and glassmorphic to match the AskTube AI product style.

---

## Storage

Analytics storage uses SQLAlchemy async models in `backend/app/analytics/models.py`.

Tables:

- `analytics_events`
- `video_metrics`
- `chat_metrics`
- `rag_metrics`

Default local/Docker configuration stores analytics in SQLite:

```dotenv
ANALYTICS_DATABASE_URL=sqlite+aiosqlite:///./data/analytics.db
```

For production PostgreSQL, set:

```dotenv
ANALYTICS_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB_NAME
```

The tables are created automatically when the FastAPI app starts and `ANALYTICS_ENABLED=true`.

---

## Prometheus Metrics

Prometheus-format metrics are exposed at:

```text
GET /metrics
GET /api/metrics
```

Current metrics include:

- `request_count`
- `http_request_duration_seconds`
- `rag_latency_seconds`
- `embedding_duration_seconds`
- `vector_query_duration_seconds`
- `processing_duration_seconds`
- `websocket_connections`
- `websocket_failures`

These metrics are separate from the dashboard database: Prometheus is for operational scraping, while the analytics dashboard is for product and AI observability.

---

## FastAPI Middleware

`AnalyticsMiddleware` automatically tracks:

- request path
- HTTP method
- status code
- request latency
- endpoint usage

It skips `/health` and `/metrics` to avoid noisy monitoring loops.

---

## LangSmith Relationship

LangSmith is still used for chain-level tracing and evaluation when enabled:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
```

The analytics dashboard complements LangSmith:

- LangSmith answers: "What happened inside a chain/tool call?"
- AskTube analytics answers: "How is the product, RAG pipeline, and UX performing over time?"

---

## Manual Checks

After starting the app:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/metrics
curl http://localhost:8000/api/analytics/dashboard
```

Then open:

```text
http://localhost:3000/analytics
```

Interact with the main app first if the dashboard is empty. Events appear after searches, video selections, ingestion, chat messages, and citation clicks.
