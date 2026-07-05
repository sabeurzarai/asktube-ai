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
