import pytest

from app.core.config import Settings
from app.services.conversation_store import (
    InMemoryConversationStore,
    PostgresConversationStore,
)
from app.services.conversation_store.factory import create_conversation_store


def test_explicit_memory_wins_over_database_url(monkeypatch):
    monkeypatch.setenv("CONVERSATION_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    assert isinstance(create_conversation_store(Settings(_env_file=None)), InMemoryConversationStore)


def test_default_derives_postgres_when_database_url_is_set(monkeypatch):
    monkeypatch.delenv("CONVERSATION_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    assert isinstance(create_conversation_store(Settings(_env_file=None)), PostgresConversationStore)


def test_default_is_memory_without_a_database_url(monkeypatch):
    monkeypatch.delenv("CONVERSATION_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert isinstance(create_conversation_store(Settings(_env_file=None)), InMemoryConversationStore)


def test_unknown_backend_raises_naming_the_value(monkeypatch):
    monkeypatch.setenv("CONVERSATION_BACKEND", "redis")
    with pytest.raises(ValueError, match="redis"):
        create_conversation_store(Settings(_env_file=None))
