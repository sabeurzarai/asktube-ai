import pytest

from app.core.config import Settings
from app.services.vector_store import InMemoryVectorStore, PgVectorStore
from app.services.vector_store.factory import create_vector_store


def test_explicit_memory_backend_wins(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    store = create_vector_store(Settings(_env_file=None))
    assert isinstance(store, InMemoryVectorStore)


def test_explicit_pgvector_backend(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    store = create_vector_store(Settings(_env_file=None))
    assert isinstance(store, PgVectorStore)


def test_chroma_backend_raises_naming_the_service_layer(monkeypatch):
    # ChromaVectorStoreService does not satisfy the VectorStore protocol (it has
    # upsert_chunks/similarity_search(query: str), not
    # replace_video_chunks/similarity_search(query_embedding: list[float])), so
    # create_vector_store() must never build one. Selecting Chroma is a
    # service-layer decision in get_vectorstore_service().
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")
    with pytest.raises(ValueError, match="service layer|get_vectorstore_service"):
        create_vector_store(Settings(_env_file=None))


def test_default_also_raises_since_default_resolves_to_chroma(monkeypatch):
    # An unset VECTOR_BACKEND resolves to "chroma" (resolve_vector_backend's
    # default), and create_vector_store() rejects "chroma" just like an explicit
    # setting would — it never silently builds a non-VectorStore.
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    with pytest.raises(ValueError, match="service layer|get_vectorstore_service"):
        create_vector_store(Settings(_env_file=None))


def test_unknown_backend_raises_naming_the_value(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "pinecone")
    with pytest.raises(ValueError, match="pinecone"):
        create_vector_store(Settings(_env_file=None))


def test_pgvector_without_database_url_raises(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ANALYTICS_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_vector_store(Settings(_env_file=None))
