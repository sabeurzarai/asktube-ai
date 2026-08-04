import pytest
from pydantic import ValidationError

from app.core.config import Settings


# CORS_ORIGINS arrives via env vars in production (Render, docker-compose).
# pydantic-settings JSON-decodes list fields from the environment unless the
# field opts out, so these tests go through the real env-source path.

def test_cors_origins_plain_single_origin_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://asktube-ai.vercel.app")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["https://asktube-ai.vercel.app"]


def test_cors_origins_comma_separated_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://asktube-ai.vercel.app")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == [
        "http://localhost:3000",
        "https://asktube-ai.vercel.app",
    ]


def test_cors_origins_json_array_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["https://asktube-ai.vercel.app","http://localhost:3000"]')
    settings = Settings(_env_file=None)
    assert settings.cors_origins == [
        "https://asktube-ai.vercel.app",
        "http://localhost:3000",
    ]


def test_cors_origins_default_when_unset(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


# DATABASE_URL is the single Postgres connection for every persistent store.
# ANALYTICS_DATABASE_URL stays as the fallback so existing deployments and
# local development keep working unchanged.

def test_database_url_takes_priority_over_analytics_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@host/db")
    monkeypatch.setenv("ANALYTICS_DATABASE_URL", "sqlite+aiosqlite:///./data/analytics.db")
    settings = Settings(_env_file=None)
    assert settings.resolved_analytics_url == "postgresql+asyncpg://u:p@host/db"


def test_analytics_url_used_when_database_url_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ANALYTICS_DATABASE_URL", "sqlite+aiosqlite:///./data/analytics.db")
    settings = Settings(_env_file=None)
    assert settings.resolved_analytics_url == "sqlite+aiosqlite:///./data/analytics.db"


def test_pool_settings_have_free_tier_defaults(monkeypatch):
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    settings = Settings(_env_file=None)
    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 5


# collection_name is a ChromaDB concept that leaked into the public API response
# schemas. The field stays; the setting behind it stops naming a backend that is
# being removed. CHROMA_COLLECTION_NAME remains a fallback so deployed
# environments keep working without an edit.

def test_vector_collection_name_takes_priority(monkeypatch):
    monkeypatch.setenv("VECTOR_COLLECTION_NAME", "new_name")
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "old_name")
    settings = Settings(_env_file=None)
    assert settings.resolved_collection_name == "new_name"


def test_chroma_collection_name_used_as_fallback(monkeypatch):
    monkeypatch.delenv("VECTOR_COLLECTION_NAME", raising=False)
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "old_name")
    settings = Settings(_env_file=None)
    assert settings.resolved_collection_name == "old_name"


def test_collection_name_default_when_neither_set(monkeypatch):
    monkeypatch.delenv("VECTOR_COLLECTION_NAME", raising=False)
    monkeypatch.delenv("CHROMA_COLLECTION_NAME", raising=False)
    settings = Settings(_env_file=None)
    assert settings.resolved_collection_name == "asktube_videos"


def test_vector_backend_defaults_to_none(monkeypatch):
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    settings = Settings(_env_file=None)
    assert settings.vector_backend is None


# A malformed DATABASE_URL previously surfaced as
# "Can't load plugin: sqlalchemy.dialects:https" from deep inside SQLAlchemy.
# That is the Supabase PROJECT url (the REST endpoint) pasted where the database
# connection string belongs - an easy mistake, since the dashboard shows it
# prominently. It cost two debugging rounds, so it fails early and by name.

def test_database_url_rejects_a_supabase_project_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "https://yskjultqsrbikvmyvwnu.supabase.co")
    with pytest.raises(ValidationError, match="postgresql"):
        Settings(_env_file=None)


def test_database_url_rejection_names_the_likely_mistake(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "https://project.supabase.co")
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    message = str(exc.value)
    assert "project url" in message.lower()
    assert "5432" in message


def test_database_url_accepts_an_asyncpg_connection_string(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@host:5432/db")
    assert Settings(_env_file=None).database_url.startswith("postgresql+asyncpg://")


def test_database_url_unset_stays_none(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert Settings(_env_file=None).database_url is None
