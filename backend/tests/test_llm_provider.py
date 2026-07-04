"""Unit tests for the chat-model factory and provider gating.

All tests are unit-level and never touch the network: the only thing they
exercise is which kwargs the factory hands to ``ChatOpenAI`` and how the
credential/tool-calling helpers branch on config. ``ChatOpenAI`` itself is
patched so no API client is constructed.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services import llm_provider
from app.services.llm_provider import (
    create_chat_model,
    require_chat_credentials,
    supports_tool_calling,
)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _openai_settings() -> Settings:
    # Explicit openai provider + key; mirrors the historical default config.
    return Settings(openai_api_key="sk-test", llm_provider="openai")


def _nvidia_settings(
    *,
    api_key: str | None = "nvapi-test",
    tool_calling: bool = True,
) -> Settings:
    return Settings(
        openai_api_key="sk-test",  # still required for embeddings/Whisper
        llm_provider="nvidia",
        nvidia_api_key=api_key,
        nvidia_chat_model="moonshotai/kimi-k2.6",
        nvidia_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_tool_calling=tool_calling,
    )


# ---------------------------------------------------------------------------
# create_chat_model
# ---------------------------------------------------------------------------

def test_openai_provider_passes_chat_model_and_openai_key_without_base_url() -> None:
    """LLM_PROVIDER unset or 'openai' → CHAT_MODEL + OPENAI_API_KEY, no base_url."""
    with patch.object(llm_provider, "ChatOpenAI") as mock_cls:
        create_chat_model(_openai_settings(), streaming=False, temperature=0.1)

    assert mock_cls.call_count == 1
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["temperature"] == 0.1
    assert kwargs["streaming"] is False
    # The OpenAI path must NOT set a custom base_url (default endpoint behavior).
    assert "base_url" not in kwargs


def test_unset_provider_defaults_to_openai() -> None:
    config = Settings(openai_api_key="sk-test")  # LLM_PROVIDER unset → default
    with patch.object(llm_provider, "ChatOpenAI") as mock_cls:
        create_chat_model(config)
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert "base_url" not in kwargs


def test_nvidia_provider_uses_nvidia_endpoint_model_and_key() -> None:
    with patch.object(llm_provider, "ChatOpenAI") as mock_cls:
        create_chat_model(_nvidia_settings(), streaming=True, temperature=0.2)

    kwargs = mock_cls.call_args.kwargs
    assert kwargs["model"] == "moonshotai/kimi-k2.6"
    assert kwargs["api_key"] == "nvapi-test"
    assert kwargs["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert kwargs["temperature"] == 0.2
    assert kwargs["streaming"] is True


def test_nvidia_provider_is_case_insensitive() -> None:
    config = Settings(
        openai_api_key="sk-test",
        llm_provider="NVIDIA",  # case shouldn't matter
        nvidia_api_key="nvapi-test",
    )
    with patch.object(llm_provider, "ChatOpenAI") as mock_cls:
        create_chat_model(config)
    assert mock_cls.call_args.kwargs["base_url"] == "https://integrate.api.nvidia.com/v1"


# ---------------------------------------------------------------------------
# require_chat_credentials
# ---------------------------------------------------------------------------

def test_openai_without_api_key_raises_503_with_openai_message() -> None:
    config = Settings(openai_api_key=None, llm_provider="openai")
    with pytest.raises(HTTPException) as exc_info:
        require_chat_credentials(config)
    assert exc_info.value.status_code == 503
    assert "OPENAI_API_KEY" in exc_info.value.detail


def test_openai_with_api_key_does_not_raise() -> None:
    require_chat_credentials(_openai_settings())  # no exception expected


def test_nvidia_without_api_key_raises_503_with_nvidia_message() -> None:
    config = _nvidia_settings(api_key=None)
    with pytest.raises(HTTPException) as exc_info:
        require_chat_credentials(config)
    assert exc_info.value.status_code == 503
    assert "NVIDIA_API_KEY" in exc_info.value.detail
    assert "LLM_PROVIDER=nvidia" in exc_info.value.detail


def test_nvidia_with_api_key_does_not_raise() -> None:
    require_chat_credentials(_nvidia_settings())  # no exception expected


# ---------------------------------------------------------------------------
# supports_tool_calling
# ---------------------------------------------------------------------------

def test_openai_always_supports_tool_calling() -> None:
    assert supports_tool_calling(_openai_settings()) is True


def test_nvidia_supports_tool_calling_follows_flag_true() -> None:
    assert supports_tool_calling(_nvidia_settings(tool_calling=True)) is True


def test_nvidia_supports_tool_calling_follows_flag_false() -> None:
    assert supports_tool_calling(_nvidia_settings(tool_calling=False)) is False
