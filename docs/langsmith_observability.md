# LangSmith Observability and Evaluation

AskTube AI uses LangSmith for tracing live RAG and agent calls, and for evaluating transcript-grounded chat behavior.

This sits beside the built-in AskTube analytics layer:

- LangSmith traces individual chains, tools, prompts, retrieved context, and failures.
- `/analytics` shows product, RAG, pipeline, UX, and business metrics over time.
- `/metrics` exposes Prometheus-format operational metrics for scraping.

For the full analytics dashboard details, see `docs/analytics_observability.md`.

---

## What Gets Traced

| Trace name | Source | Run type |
|---|---|---|
| `rag_answer` | `RAGService.answer()` | chain |
| `rag_stream_answer` | `RAGService.stream_answer()` | chain |
| `rag_prepare_context` | `RAGService.prepare_context()` | retriever |
| `agent_chat` | `AgentService.chat()` | chain |
| `rag_evaluation` | `LangSmithEvaluationService.evaluate_rag()` | chain |
| `conversation_evaluation` | `LangSmithEvaluationService.evaluate_conversation()` | chain |

All traces include metadata: `video_id`, `session_id`, `top_k`, `context_chunks`. This lets you move from a bad answer directly to the exact retrieval payload in the LangSmith UI.

---

## Environment

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your_langsmith_key
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=AskTube-AI
LANGSMITH_EVAL_PROJECT=AskTube-AI-Evals
LANGSMITH_LATENCY_BUDGET_MS=8000
HALLUCINATION_RISK_THRESHOLD=0.35
RAG_EVALUATOR_MODE=heuristic
```

`LANGCHAIN_TRACING_V2` and `LANGCHAIN_PROJECT` are also supported for compatibility with LangChain's own tracing settings. Set `LANGSMITH_TRACING=false` for local development without tracing.

---

## RAG Debugging

Call the direct chat endpoint and inspect the trace in LangSmith:

```http
POST /api/chat
Content-Type: application/json

{
  "message": "What is the main idea?",
  "video_id": "kqtD5dpn9C8",
  "top_k": 5
}
```

Or the agent endpoint (includes tool call traces):

```http
POST /api/agent/chat
Content-Type: application/json

{
  "message": "What is Python used for?",
  "video_id": "kqtD5dpn9C8"
}
```

The LangSmith trace shows:
- which tools the agent called and in what order
- retrieved transcript chunks with timestamps
- context injected into the prompt
- conversation memory passed to the model
- model latency per step
- final answer and citations

---

## Latency Analysis

```http
POST /api/evaluations/rag
Content-Type: application/json

{
  "message": "What is the main idea?",
  "video_id": "kqtD5dpn9C8",
  "top_k": 5
}
```

The response includes `latency_ms`, `latency_budget_ms` (default 8000ms), and `latency_passed`.

---

## Hallucination Detection

The heuristic evaluator checks:

- answer term overlap against retrieved transcript text (groundedness score)
- unsupported numbers and named terms not present in context
- citation presence and timestamp format
- context coverage (fraction of retrieved chunks cited)

Returns a `hallucination_risk` score from `0.0` to `1.0`. Lower is better. Threshold is `HALLUCINATION_RISK_THRESHOLD` (default 0.35).

**Note on heuristic accuracy:** The term-overlap scorer is conservative - it flags paraphrased-but-correct answers as moderate risk because the exact terms differ from the retrieved chunks. Set `RAG_EVALUATOR_MODE=llm` to use an LLM-based evaluator for higher-accuracy scoring (requires additional API calls).

---

## Conversational Testing

```http
POST /api/evaluations/conversation
Content-Type: application/json

{
  "video_id": "kqtD5dpn9C8",
  "top_k": 5,
  "turns": [
    { "message": "What are the main data types in Python?" },
    { "message": "How do you convert between those types?" },
    { "message": "Give me the timestamp for when type conversion is explained." }
  ]
}
```

The response reports average latency, average groundedness, and failed turn indices.

---

## AskTube Dashboard vs LangSmith

| Question | Best tool |
|---|---|
| Which tool did the agent call for this one answer? | LangSmith trace |
| Which transcript chunks went into this one prompt? | LangSmith trace |
| How many users searched or chatted today? | AskTube `/analytics` dashboard |
| Is RAG latency improving or getting worse? | AskTube `/analytics` dashboard and `/metrics` |
| Are WebSocket ingestion failures happening? | Prometheus `/metrics` and backend logs |
| Why did one answer fail? | LangSmith trace + evaluation endpoint |

The two systems are complementary: LangSmith is deep inspection for AI calls, while AskTube analytics is the product/platform overview.

---

## Evaluation Dataset and CLI Runner

A 17-case evaluation dataset is included at `backend/tests/fixtures/rag_eval_cases.json`. It covers:

- answerable transcript questions (5 cases)
- off-topic refusals (4 cases)
- citation timestamp accuracy (2 cases)
- summary generation (2 cases)
- hallucination prevention (2 cases)
- multi-turn memory (2 conversation cases)

Run all cases locally:

```bash
cd backend
python scripts/run_evaluation.py
```

**Prerequisites:** Video `kqtD5dpn9C8` must be ingested in ChromaDB first (`POST /api/videos/kqtD5dpn9C8/ingest`). `OPENAI_API_KEY` must be set.

**Exit codes:** `0` = all cases pass or warn, `1` = at least one hard FAIL (wrong behavior, forbidden hallucinated term, or missing expected content).

**Interpreting results:**
- `PASS` - all behavioral and content assertions satisfied; metrics within threshold
- `WARN` - correct behavior but heuristic metrics below threshold (expected for paraphrased answers)
- `FAIL` - hard assertion failed: model answered when it should have refused, hallucinated a forbidden term, or omitted required content
