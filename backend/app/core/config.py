from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    chunk_max_chars: int = Field(default=1200, alias="CHUNK_MAX_CHARS")
    chunk_overlap_segments: int = Field(default=1, alias="CHUNK_OVERLAP_SEGMENTS")
    chroma_host: str = Field(default="localhost", alias="CHROMA_HOST")
    chroma_port: int = Field(default=8001, alias="CHROMA_PORT")
    chroma_use_http: bool = Field(default=False, alias="CHROMA_USE_HTTP")
    chroma_persist_dir: str = Field(default="./chroma_data", alias="CHROMA_PERSIST_DIR")
    chroma_collection_name: str = Field(
        default="asktube_videos",
        alias="CHROMA_COLLECTION_NAME",
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
    analytics_enabled: bool = Field(default=True, alias="ANALYTICS_ENABLED")
    prometheus_enabled: bool = Field(default=True, alias="PROMETHEUS_ENABLED")
    langchain_tracing_v2: bool | None = Field(default=None, alias="LANGCHAIN_TRACING_V2")
    langchain_project: str | None = Field(default=None, alias="LANGCHAIN_PROJECT")
    cors_origins: list[str] = Field(
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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
