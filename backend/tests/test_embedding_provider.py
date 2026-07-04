"""Unit tests for the embedding factory and provider gating.

Mirrors test_llm_provider.py: all tests are unit-level and network-free.
``HuggingFaceEmbeddings`` is patched so no torch/model download happens, and
``OpenAIEmbeddings`` is patched so no API client is constructed.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services import embedding_provider
from app.services.embedding_provider import (
    create_embeddings,
    require_embedding_credentials,
)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _openai_settings(api_key: str | None = "sk-test") -> Settings:
    return Settings(openai_api_key=api_key, embedding_provider="openai")


def _local_settings(model: str = "sentence-transformers/all-MiniLM-L6-v2") -> Settings:
    return Settings(
        openai_api_key=None,  # local mode must not require any OpenAI key
        embedding_provider="local",
        local_embedding_model=model,
    )


@pytest.fixture(autouse=True)
def _clear_local_cache():
    """Reset the HuggingFaceEmbeddings cache between tests so stubs don't leak."""
    embedding_provider._local_cache.clear()
    yield
    embedding_provider._local_cache.clear()


# ---------------------------------------------------------------------------
# create_embeddings
# ---------------------------------------------------------------------------

def test_openai_provider_builds_openai_embeddings_with_model_and_key() -> None:
    """EMBEDDING_PROVIDER unset or 'openai' → OpenAIEmbeddings(model, api_key)."""
    with patch("langchain_openai.OpenAIEmbeddings") as mock_oai:
        create_embeddings(_openai_settings(api_key="sk-test"))

    kwargs = mock_oai.call_args.kwargs
    assert kwargs["model"] == "text-embedding-3-small"
    assert kwargs["api_key"] == "sk-test"


def test_unset_provider_defaults_to_openai() -> None:
    config = Settings(openai_api_key="sk-test")  # EMBEDDING_PROVIDER unset
    with patch("langchain_openai.OpenAIEmbeddings") as mock_oai:
        create_embeddings(config)
    assert mock_oai.call_args.kwargs["model"] == "text-embedding-3-small"


def test_local_provider_builds_huggingface_embeddings() -> None:
    """EMBEDDING_PROVIDER=local → HuggingFaceEmbeddings(model_name=...)."""
    with patch("langchain_huggingface.HuggingFaceEmbeddings") as mock_hf:
        create_embeddings(_local_settings())

    assert mock_hf.call_args.kwargs["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"


def test_local_provider_passes_configured_model() -> None:
    config = _local_settings(model="sentence-transformers/all-mpnet-base-v2")
    with patch("langchain_huggingface.HuggingFaceEmbeddings") as mock_hf:
        create_embeddings(config)
    assert mock_hf.call_args.kwargs["model_name"] == "sentence-transformers/all-mpnet-base-v2"


def test_local_provider_is_case_insensitive() -> None:
    config = Settings(openai_api_key=None, embedding_provider="LOCAL")
    with patch("langchain_huggingface.HuggingFaceEmbeddings") as mock_hf:
        create_embeddings(config)
    assert mock_hf.call_count == 1


def test_local_provider_caches_instance_per_model() -> None:
    """Repeated calls with the same model return the same cached instance."""
    with patch("langchain_huggingface.HuggingFaceEmbeddings") as mock_hf:
        mock_hf.return_value = MagicMock(name="cached")
        first = create_embeddings(_local_settings())
        second = create_embeddings(_local_settings())

    assert first is second
    assert mock_hf.call_count == 1  # constructed only once


# ---------------------------------------------------------------------------
# require_embedding_credentials
# ---------------------------------------------------------------------------

def test_openai_without_api_key_raises_503() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_embedding_credentials(_openai_settings(api_key=None))
    assert exc_info.value.status_code == 503
    assert "OPENAI_API_KEY" in exc_info.value.detail


def test_openai_with_api_key_does_not_raise() -> None:
    require_embedding_credentials(_openai_settings(api_key="sk-test"))


def test_local_never_requires_credentials() -> None:
    """Local mode runs without any API key — must not raise even when key is None."""
    require_embedding_credentials(_local_settings())  # no exception expected
