"""Chat-model factory and provider-gating for AskTube AI.

This is the single place chat models are built. It supports the default
OpenAI provider and an optional NVIDIA (NIM, OpenAI-compatible) provider so
that chat generation can run against ``https://integrate.api.nvidia.com/v1``
while embeddings and Whisper stay on OpenAI.
"""

from fastapi import HTTPException, status
from langchain_openai import ChatOpenAI

from app.core.config import Settings

# Anything not explicitly "nvidia" falls back to OpenAI, which keeps the
# default behavior byte-for-byte when LLM_PROVIDER is unset.
NVIDIA_PROVIDER = "nvidia"


def _is_nvidia(config: Settings) -> bool:
    return (config.llm_provider or "").strip().lower() == NVIDIA_PROVIDER


def create_chat_model(
    config: Settings,
    *,
    streaming: bool = False,
    temperature: float = 0.1,
) -> ChatOpenAI:
    """Build the chat model for the active provider.

    NVIDIA mode targets the OpenAI-compatible NIM endpoint using the NVIDIA
    key and model. Everything else reproduces the previous OpenAI behavior.
    """
    if _is_nvidia(config):
        return ChatOpenAI(
            model=config.nvidia_chat_model,
            api_key=config.nvidia_api_key,
            base_url=config.nvidia_base_url,
            temperature=temperature,
            streaming=streaming,
        )

    return ChatOpenAI(
        model=config.chat_model,
        api_key=config.openai_api_key,
        temperature=temperature,
        streaming=streaming,
    )


def require_chat_credentials(config: Settings) -> None:
    """Raise a 503 with a provider-specific message if chat creds are missing.

    OpenAI mode keeps the historical "OPENAI_API_KEY is required" wording so
    existing tests and error handling continue to match.
    """
    if _is_nvidia(config):
        if not config.nvidia_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="NVIDIA_API_KEY is required when LLM_PROVIDER=nvidia.",
            )
        return

    if not config.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is required.",
        )


def supports_tool_calling(config: Settings) -> bool:
    """Whether the active provider should drive the tool-calling agent.

    Always true for OpenAI. For NVIDIA it follows ``NVIDIA_TOOL_CALLING`` so
    flaky tool-calling models can opt out and fall back to plain RAG.
    """
    if _is_nvidia(config):
        return bool(config.nvidia_tool_calling)
    return True
