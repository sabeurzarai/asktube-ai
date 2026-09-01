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


def test_default_derives_pgvector_when_database_url_is_set(monkeypatch):
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    store = create_vector_store(Settings(_env_file=None))
    assert isinstance(store, PgVectorStore)


def test_default_is_memory_without_a_database_url(monkeypatch):
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = create_vector_store(Settings(_env_file=None))
    assert isinstance(store, InMemoryVectorStore)


def test_chroma_is_no_longer_a_valid_backend(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")
    with pytest.raises(ValueError, match="removed"):
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


def test_pgvector_engine_uses_the_shared_engine_options(monkeypatch) -> None:  # noqa: ANN001
    """The vector store must not hand-roll its engine options.

    It did, and it drifted: it set `statement_cache_size: 0` alone while
    build_engine_kwargs sets three connect args and documents, in a comment, that
    all three are "applied unconditionally to every Postgres engine this app
    builds". That was untrue for the two engines the product actually depends on
    - this one and the conversation store - so the collision that the other two
    args prevent (`__asyncpg_stmt_N__` reused across pooled connections) was
    still reachable here, and it fails intermittently under concurrency rather
    than at startup, which is the hardest way to notice anything.
    """
    import app.services.vector_store.factory as factory_module
    from app.analytics.database import build_engine_kwargs

    captured: dict = {}

    def fake_create_async_engine(url, **kwargs):  # noqa: ANN001, ANN202
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(factory_module, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(factory_module, "async_sessionmaker", lambda **kw: object())  # noqa: ARG005
    monkeypatch.setattr(factory_module, "PgVectorStore", lambda factory: factory)  # noqa: ARG005

    config = Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://u:p@host/db")
    factory_module.create_vector_store(config)

    expected = build_engine_kwargs(config.database_url, config)
    assert captured["kwargs"]["pool_recycle"] == expected["pool_recycle"]
    connect_args = captured["kwargs"]["connect_args"]
    assert connect_args["statement_cache_size"] == 0
    assert connect_args["prepared_statement_cache_size"] == 0
    assert callable(connect_args["prepared_statement_name_func"])
