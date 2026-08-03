import pytest

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
