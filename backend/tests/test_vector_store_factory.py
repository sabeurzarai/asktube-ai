import pytest

from app.core.config import Settings
from app.services.vector_store import InMemoryVectorStore, PgVectorStore
from app.services.vector_store.factory import create_vector_store
from app.services.vectorstore_service import ChromaVectorStoreService


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


def test_default_is_chroma_while_chroma_exists(monkeypatch):
    # Deliberate: the derived default arrives in Phase 2b-ii, after Chroma is
    # deleted. Until then, merging must not switch production backends.
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    store = create_vector_store(Settings(_env_file=None))
    assert isinstance(store, ChromaVectorStoreService)


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
