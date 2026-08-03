from app.analytics.database import build_engine_kwargs
from app.core.config import Settings


def test_postgres_gets_pool_sizing_and_disabled_statement_cache():
    config = Settings(_env_file=None, DB_POOL_SIZE=7, DB_MAX_OVERFLOW=3)
    kwargs = build_engine_kwargs("postgresql+asyncpg://u:p@host/db", config)
    assert kwargs["pool_size"] == 7
    assert kwargs["max_overflow"] == 3
    assert kwargs["pool_pre_ping"] is True
    # Supavisor (Supabase transaction pooler) cannot carry prepared statements.
    assert kwargs["connect_args"] == {"statement_cache_size": 0}


def test_sqlite_omits_pool_sizing_and_connect_args():
    config = Settings(_env_file=None)
    kwargs = build_engine_kwargs("sqlite+aiosqlite:///./data/analytics.db", config)
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs
    assert "connect_args" not in kwargs
    assert kwargs["pool_pre_ping"] is True
