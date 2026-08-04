from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AskTube AI"
    app_version: str = "0.1.0"
    youtube_api_key: str | None = Field(default=None, alias="YOUTUBE_API_KEY")
    youtube_api_base_url: str = "https://www.googleapis.com/youtube/v3"
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    whisper_model: str = Field(default="whisper-1", alias="WHISPER_MODEL")
    chat_model: str = Field(default="gpt-4o-mini", alias="CHAT_MODEL")
    # ── Chat model provider ───────────────────────────────────────────────────
    # "openai" (default) or "nvidia". NVIDIA mode replaces CHAT generation only;
    # embeddings + Whisper always use OpenAI (OPENAI_API_KEY stays required).
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    nvidia_api_key: str | None = Field(default=None, alias="NVIDIA_API_KEY")
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        alias="NVIDIA_BASE_URL",
    )
    nvidia_chat_model: str = Field(
        default="moonshotai/kimi-k2.6",
        alias="NVIDIA_CHAT_MODEL",
    )
    # Set false if the chosen NVIDIA model's tool calling misbehaves — the agent
    # then falls back to plain RAG instead of bind_tools.
    nvidia_tool_calling: bool = Field(default=True, alias="NVIDIA_TOOL_CALLING")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    # ── Embedding provider ─────────────────────────────────────────────────────
    # "openai" (default) or "local". Local mode runs a HuggingFace
    # sentence-transformers model on the CPU — fully free, no API calls, but
    # changing providers changes vector dimensions: the transcript_chunks column
    # is a fixed-width vector(N), so switching needs a new migration plus a wipe
    # and re-ingest of all videos, or retrieval returns garbage.
    embedding_provider: str = Field(default="openai", alias="EMBEDDING_PROVIDER")
    local_embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="LOCAL_EMBEDDING_MODEL",
    )
    chunk_max_chars: int = Field(default=1200, alias="CHUNK_MAX_CHARS")
    chunk_overlap_segments: int = Field(default=1, alias="CHUNK_OVERLAP_SEGMENTS")
    # Survives only as a compatibility alias: the ChromaDB backend is gone, but
    # CHROMA_COLLECTION_NAME remains the fallback behind VECTOR_COLLECTION_NAME
    # for deployments that still set it (see resolved_collection_name below).
    chroma_collection_name: str = Field(
        default="asktube_videos",
        alias="CHROMA_COLLECTION_NAME",
    )
    vector_collection_name: str | None = Field(
        default=None,
        alias="VECTOR_COLLECTION_NAME",
        description=(
            "Logical name reported as collection_name in API responses. Replaces "
            "CHROMA_COLLECTION_NAME, which stays as a fallback."
        ),
    )
    vector_backend: str | None = Field(
        default=None,
        alias="VECTOR_BACKEND",
        description=(
            "Explicit vector store backend: 'pgvector' or 'memory'. Unset derives "
            "from DATABASE_URL: set means pgvector, absent means memory."
        ),
    )
    conversation_backend: str | None = Field(
        default=None,
        alias="CONVERSATION_BACKEND",
        description=(
            "Explicit conversation store backend: 'postgres' or 'memory'. Unset "
            "derives from DATABASE_URL: set means postgres, absent means memory."
        ),
    )
    audio_cache_dir: str = Field(default="data/audio_cache", alias="AUDIO_CACHE_DIR")
    ffmpeg_location: str | None = Field(default=None, alias="FFMPEG_LOCATION")
    webshare_proxy_username: str | None = Field(
        default=None,
        alias="WEBSHARE_PROXY_USERNAME",
    )
    webshare_proxy_password: str | None = Field(
        default=None,
        alias="WEBSHARE_PROXY_PASSWORD",
    )
    webshare_proxy_url: str | None = Field(
        default=None,
        alias="WEBSHARE_PROXY_URL",
        description=(
            "Optional complete Webshare proxy URL, for example the URL from the "
            "Webshare Proxy Integration curl snippet."
        ),
    )
    webshare_proxy_locations: str | None = Field(
        default=None,
        alias="WEBSHARE_PROXY_LOCATIONS",
        description="Optional comma-separated country codes for Webshare residential proxies.",
    )
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_api_key: str | None = Field(default=None, alias="LANGSMITH_API_KEY")
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        alias="LANGSMITH_ENDPOINT",
    )
    langsmith_project: str = Field(default="AskTube-AI", alias="LANGSMITH_PROJECT")
    langsmith_eval_project: str = Field(
        default="AskTube-AI-Evals",
        alias="LANGSMITH_EVAL_PROJECT",
    )
    langsmith_latency_budget_ms: int = Field(
        default=8000,
        alias="LANGSMITH_LATENCY_BUDGET_MS",
    )
    hallucination_risk_threshold: float = Field(
        default=0.35,
        alias="HALLUCINATION_RISK_THRESHOLD",
    )
    rag_evaluator_mode: Literal["heuristic", "llm"] = Field(
        default="heuristic",
        alias="RAG_EVALUATOR_MODE",
    )
    analytics_database_url: str = Field(
        default="sqlite+aiosqlite:///./data/analytics.db",
        alias="ANALYTICS_DATABASE_URL",
        description="Async SQLAlchemy URL for analytics storage. Use PostgreSQL in production.",
    )
    database_url: str | None = Field(
        default=None,
        alias="DATABASE_URL",
        description=(
            "Single async SQLAlchemy URL for all persistent stores. When set it "
            "takes priority over ANALYTICS_DATABASE_URL. Example: "
            "postgresql+asyncpg://user:password@host:6543/postgres"
        ),
    )
    db_pool_size: int = Field(
        default=5,
        alias="DB_POOL_SIZE",
        description="Kept small: Supabase Free caps connections and Render's free container is memory-constrained.",
    )
    db_max_overflow: int = Field(
        default=5,
        alias="DB_MAX_OVERFLOW",
        description="Additional connections allowed beyond db_pool_size under burst.",
    )
    analytics_enabled: bool = Field(default=True, alias="ANALYTICS_ENABLED")
    prometheus_enabled: bool = Field(default=True, alias="PROMETHEUS_ENABLED")
    langchain_tracing_v2: bool | None = Field(default=None, alias="LANGCHAIN_TRACING_V2")
    langchain_project: str | None = Field(default=None, alias="LANGCHAIN_PROJECT")
    # NoDecode: stop pydantic-settings from JSON-decoding the env value before
    # parse_cors_origins runs — otherwise a plain comma-separated CORS_ORIGINS
    # (the format .env.example documents) crashes startup with a SettingsError.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        alias="CORS_ORIGINS",
        description="Comma-separated list of allowed CORS origins.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    def __init__(self, **data):
        # pydantic-settings gives aliases priority for environment-backed fields.
        # Tests and dependency overrides use Pythonic snake_case names, so map
        # explicit field-name overrides to their env aliases before settings
        # sources are resolved.
        for field_name, field_info in self.__class__.model_fields.items():
            alias = field_info.alias
            if alias and field_name in data and alias not in data:
                data[alias] = data.pop(field_name)
        super().__init__(**data)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            stripped = value.strip()
            # Accept JSON array: '["http://...","http://..."]'
            if stripped.startswith("["):
                import json
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [o.strip() for o in parsed if isinstance(o, str) and o.strip()]
                except json.JSONDecodeError:
                    pass
            # Accept comma-separated: "http://...,http://..."
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]

        return value

    @property
    def webshare_proxy_location_list(self) -> list[str]:
        if not self.webshare_proxy_locations:
            return []

        return [
            location.strip().upper()
            for location in self.webshare_proxy_locations.split(",")
            if location.strip()
        ]

    @field_validator("database_url", mode="after")
    @classmethod
    def reject_non_postgres_database_url(cls, value: str | None) -> str | None:
        """Fail early and by name on a URL that is not a Postgres connection string.

        Without this, pasting the Supabase PROJECT url here surfaces much later as
        `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:https` from deep
        inside SQLAlchemy - which names neither the setting nor the mistake. The
        project url is shown prominently in the dashboard, so it is the natural
        thing to copy; it is the REST endpoint, not the database.
        """
        if value is None or value.startswith("postgresql"):
            return value

        hint = ""
        if value.startswith("http"):
            hint = (
                " That looks like a Supabase project url (the REST endpoint), not a "
                "database connection string. Copy the port-5432 entry from Supabase "
                "-> Connect and change the scheme to postgresql+asyncpg://."
            )

        raise ValueError(
            f"DATABASE_URL must be a PostgreSQL connection string starting with "
            f"'postgresql+asyncpg://', got {value[:40]!r}.{hint}"
        )

    @property
    def resolved_analytics_url(self) -> str:
        """DATABASE_URL wins; ANALYTICS_DATABASE_URL is the backwards-compatible fallback."""
        return self.database_url or self.analytics_database_url

    @property
    def resolved_collection_name(self) -> str:
        """VECTOR_COLLECTION_NAME wins; CHROMA_COLLECTION_NAME is the fallback."""
        return self.vector_collection_name or self.chroma_collection_name


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
