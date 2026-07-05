"""Embeddings factory and provider-gating for AskTube AI.

This is the single place embeddings are built. It supports the default
OpenAI provider and an optional free "local" provider that runs a
HuggingFace sentence-transformers model on the CPU.

Switching providers changes vector dimensions, so any ChromaDB collection
populated under one provider MUST be wiped before querying under the other
— otherwise retrieval silently returns garbage.
"""

from fastapi import HTTPException, status
from langchain_core.embeddings import Embeddings

from app.core.config import Settings

# Anything not explicitly "local" falls back to OpenAI, which keeps the
# default behavior byte-for-byte when EMBEDDING_PROVIDER is unset.
LOCAL_PROVIDER = "local"


def _is_local(config: Settings) -> bool:
    return (config.embedding_provider or "").strip().lower() == LOCAL_PROVIDER


def _import_local_embeddings():
    """Import the optional HuggingFaceEmbeddings class.

    Isolated in its own function so it can be cleanly patched in tests, and so
    the heavy torch/sentence-transformers import only happens when local
    embeddings are actually selected. Raises ImportError when the optional
    extras are not installed.
    """
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings


# HuggingFaceEmbeddings loads the model lazily on first use, but constructing
# it is still cheap-ish (~tens of ms for the wrapper; the ~3s model load
# happens on first embed). We cache a single instance per process so the
# heavy model load happens exactly once.
_local_cache: dict[tuple[str], Embeddings] = {}


def create_embeddings(config: Settings) -> Embeddings:
    """Build the embedding model for the active provider.

    Local mode returns a CPU-backed HuggingFace sentence-transformers model
    (no API calls, fully free). Everything else reproduces the previous
    OpenAI behavior.
    """
    if _is_local(config):
        # Cache keyed by model name so switching LOCAL_EMBEDDING_MODEL at
        # runtime (tests) doesn't return a stale instance.
        cache_key = (config.local_embedding_model,)
        cached = _local_cache.get(cache_key)
        if cached is not None:
            return cached
        # The local-embeddings extras are OPTIONAL. Import lazily so the heavy
        # torch/sentence-transformers load only happens when local embeddings
        # are actually selected, and fail with an actionable message naming the
        # file to install if EMBEDDING_PROVIDER=local was set without them.
        try:
            huggingface_embeddings_cls = _import_local_embeddings()
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "EMBEDDING_PROVIDER=local requires the optional local-"
                    "embeddings extras. Install them with: "
                    "pip install -r requirements-local-embeddings.txt"
                ),
            ) from exc

        embeddings = huggingface_embeddings_cls(model_name=config.local_embedding_model)
        _local_cache[cache_key] = embeddings
        return embeddings

    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=config.embedding_model,
        api_key=config.openai_api_key,
    )


def require_embedding_credentials(config: Settings) -> None:
    """Raise a 503 if embedding credentials are missing for the active provider.

    Local mode needs no credentials. OpenAI mode keeps the historical
    "OPENAI_API_KEY is required" wording so existing tests and error
    handling continue to match.
    """
    if _is_local(config):
        return

    if not config.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is required.",
        )
