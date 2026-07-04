# Prompt: Add optional NVIDIA NIM chat provider to AskTube AI

Implement optional NVIDIA AI endpoint support for AskTube AI as an alternative **chat** model provider. Make the smallest possible change, follow existing project patterns, and add no new dependencies.

## Goal

Allow AskTube AI to use either OpenAI or NVIDIA's OpenAI-compatible API (`https://integrate.api.nvidia.com/v1`) for chat generation, without breaking the existing RAG pipeline, citations, memory, tools, analytics, Whisper fallback, or embeddings.

## Verified codebase facts (do not rediscover — these are checked)

- Chat models are constructed in exactly **two** places:
  - `backend/app/services/rag_service.py` → `RAGService.create_chat_model()` (~line 257)
  - `backend/app/services/agent_service.py` → `ChatOpenAI(...).bind_tools(self.tools)` (~line 79)
- Provider-gating key checks that must become provider-aware (both currently raise 503 "OPENAI_API_KEY is required"):
  - `backend/app/services/rag_service.py` ~line 242
  - `backend/app/services/agent_service.py` ~line 72
- **Out of scope — must NOT change** (they keep using `OPENAI_API_KEY`):
  - Embeddings: `OpenAIEmbeddings` in `chunking_service.py` and `vectorstore_service.py`. ChromaDB collections were embedded with `text-embedding-3-small`; changing this silently breaks retrieval for already-ingested videos.
  - Whisper/speech: `AsyncOpenAI` in `transcript_service.py` and `app/api/routes/speech.py`.
- Config lives in `backend/app/core/config.py` (pydantic-settings, `Field(alias="ENV_NAME")` style, `extra="ignore"`).
- `langchain-openai==1.2.1` is already a dependency. `ChatOpenAI(base_url=..., api_key=..., model=...)` is the documented LangChain pattern for OpenAI-compatible endpoints. Do **not** add `langchain-nvidia-ai-endpoints`.
- `backend/tests/test_agent_service.py` patches `app.services.agent_service.ChatOpenAI` in ~10 places. **Updating those patch targets to the new factory module is expected and allowed** — that is not a regression.
- Docker: `docker-compose.yml` passes the whole `.env` into the backend via `env_file`, so the new variables need **no compose changes**. Do not add them under `environment:` (keys there override `env_file`).

## Environment variables

Add (both `.env.example` at repo root and `backend/.env.example`):

```dotenv
# ── Chat model provider ───────────────────────────────────────────────────────
# "openai" (default) or "nvidia". NVIDIA mode replaces CHAT generation only.
# OPENAI_API_KEY remains REQUIRED in all modes (embeddings + Whisper still use OpenAI).
LLM_PROVIDER=openai
# Get a free key at https://build.nvidia.com (free endpoints are rate-limited — fine
# for demos, not production traffic).
NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
# Any build.nvidia.com model tagged "Tool Use" works. Recommended default:
NVIDIA_CHAT_MODEL=moonshotai/kimi-k2.6
# Alternatives: deepseek-ai/deepseek-v4-flash (fastest), z-ai/glm-5.2 (newest flagship)
# Set false if the chosen model's tool calling misbehaves — agent falls back to plain RAG.
NVIDIA_TOOL_CALLING=true
```

Keep all existing OpenAI variables unchanged (`OPENAI_API_KEY`, `CHAT_MODEL`, `EMBEDDING_MODEL`, `WHISPER_MODEL`).

## Security requirements

- No hardcoded API keys anywhere. No secrets committed. Environment variables only.
- Before finishing, grep the diff for `nvapi-` and `sk-` to confirm nothing leaked.

## Implementation plan

1. **`backend/app/core/config.py`** — add fields following the existing alias style:
   - `llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")`
   - `nvidia_api_key: str | None = Field(default=None, alias="NVIDIA_API_KEY")`
   - `nvidia_base_url: str = Field(default="https://integrate.api.nvidia.com/v1", alias="NVIDIA_BASE_URL")`
   - `nvidia_chat_model: str = Field(default="moonshotai/kimi-k2.6", alias="NVIDIA_CHAT_MODEL")`
   - `nvidia_tool_calling: bool = Field(default=True, alias="NVIDIA_TOOL_CALLING")`

2. **New `backend/app/services/llm_provider.py`** — the single place chat models are built:
   - `create_chat_model(config, *, streaming: bool = False, temperature: float = 0.1) -> ChatOpenAI`
     - `nvidia` → `ChatOpenAI(model=config.nvidia_chat_model, api_key=config.nvidia_api_key, base_url=config.nvidia_base_url, temperature=temperature, streaming=streaming)`
     - anything else → exactly the current behavior: `ChatOpenAI(model=config.chat_model, api_key=config.openai_api_key, temperature=temperature, streaming=streaming)`
   - `require_chat_credentials(config) -> None` — raises `HTTPException(503)` with a provider-specific message: nvidia without `NVIDIA_API_KEY` → `"NVIDIA_API_KEY is required when LLM_PROVIDER=nvidia."`; openai without `OPENAI_API_KEY` → keep the current message.
   - `supports_tool_calling(config) -> bool` — `True` for openai; `config.nvidia_tool_calling` for nvidia.

3. **`backend/app/services/rag_service.py`** — `create_chat_model` delegates to the new factory; replace the ~line-242 key check with `require_chat_credentials`. No other logic changes; answers stay transcript-grounded with timestamp citations.

4. **`backend/app/services/agent_service.py`** — replace the key check (~line 72) with `require_chat_credentials` and the `ChatOpenAI(...)` construction (~line 79) with the factory. If `supports_tool_calling(config)` is `False`, **do not build a new pipeline**: delegate to the existing `rag_service` retrieval + generation path and return an `AgentChatResponse` with the RAG answer, its citations, and `tool_steps_used=[]`. Off-topic refusal behavior comes with the existing RAG prompt — do not reimplement it.

5. **Docs** — short "NVIDIA provider (optional)" section in `README.md` and `DEPLOY.md`: get a key at build.nvidia.com, set `LLM_PROVIDER=nvidia` + `NVIDIA_API_KEY` in `.env`, restart the backend (`docker compose up -d --build backend` per existing docs); note the free-endpoint rate limits and that `OPENAI_API_KEY` is still required for embeddings/Whisper.

6. **Tests** — new `backend/tests/test_llm_provider.py` plus targeted updates (all unit-level; never call the network):
   - `LLM_PROVIDER` unset or `openai` → factory returns a model configured with `CHAT_MODEL` + `OPENAI_API_KEY` and **no** custom base_url (assert constructor kwargs).
   - `LLM_PROVIDER=nvidia` → constructor receives `NVIDIA_BASE_URL`, `NVIDIA_CHAT_MODEL`, `NVIDIA_API_KEY`.
   - `LLM_PROVIDER=nvidia` with no `NVIDIA_API_KEY` → `require_chat_credentials` raises 503 with the helpful message.
   - `nvidia_tool_calling=False` → agent path returns a response with citations without calling `bind_tools` (assert the fallback delegates to the RAG service).
   - Update the `patch("app.services.agent_service.ChatOpenAI")` targets in `test_agent_service.py` to the factory's module (e.g. `app.services.llm_provider.ChatOpenAI`).
   - Existing RAG citation tests must still pass unchanged.

## Acceptance criteria

- `LLM_PROVIDER=openai` or unset → behavior is byte-for-byte the current behavior; all existing tests pass.
- `LLM_PROVIDER=nvidia` + `NVIDIA_API_KEY` set → chat and agent endpoints use the NVIDIA endpoint; citations preserved.
- `LLM_PROVIDER=nvidia` without `NVIDIA_API_KEY` → clear 503 config error naming the missing variable.
- Embeddings still use OpenAI `text-embedding-3-small`; Whisper still uses OpenAI.
- No keys committed; frontend unchanged; `docker-compose.yml` unchanged.
- Full backend test suite passes — paste the actual pytest output, do not just claim it.
