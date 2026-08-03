from app.analytics.database import build_engine_kwargs
from app.core.config import Settings
import app.analytics.database as db_module


def test_postgres_gets_pool_sizing_and_disabled_statement_cache():
    config = Settings(_env_file=None, DB_POOL_SIZE=7, DB_MAX_OVERFLOW=3)
    kwargs = build_engine_kwargs("postgresql+asyncpg://u:p@host/db", config)
    assert kwargs["pool_size"] == 7
    assert kwargs["max_overflow"] == 3
    assert kwargs["pool_pre_ping"] is True
    # statement_cache_size=0 alone only disables asyncpg's own cache.
    # SQLAlchemy's asyncpg dialect keeps a second prepared-statement layer
    # (its own cache size + a numeric name generator) that must also be
    # neutralized, or pooled connections collide on generated statement names.
    connect_args = kwargs["connect_args"]
    assert connect_args["statement_cache_size"] == 0
    assert connect_args["prepared_statement_cache_size"] == 0
    name_func = connect_args["prepared_statement_name_func"]
    assert callable(name_func)
    # The property that matters: successive calls must not collide.
    assert name_func() != name_func()


def test_sqlite_omits_pool_sizing_and_connect_args():
    config = Settings(_env_file=None)
    kwargs = build_engine_kwargs("sqlite+aiosqlite:///./data/analytics.db", config)
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs
    assert "connect_args" not in kwargs
    assert kwargs["pool_pre_ping"] is True


async def test_init_creates_tables_on_sqlite(monkeypatch):
    called = {"create_all": False}

    class FakeConnection:
        async def run_sync(self, _fn):
            called["create_all"] = True

    class FakeBegin:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, *_args):
            return False

    class FakeEngine:
        url = "sqlite+aiosqlite:///./data/analytics.db"

        def begin(self):
            return FakeBegin()

    monkeypatch.setattr(db_module, "engine", FakeEngine())
    monkeypatch.setattr(db_module.settings, "database_url", None)
    await db_module.init_analytics_db()
    assert called["create_all"] is True


async def test_init_skips_create_all_on_postgres(monkeypatch):
    called = {"create_all": False}

    class FakeEngine:
        def begin(self):  # pragma: no cover - must never be reached
            called["create_all"] = True
            raise AssertionError("create_all must not run against postgres")

    monkeypatch.setattr(db_module, "engine", FakeEngine())
    monkeypatch.setattr(db_module.settings, "database_url", "postgresql+asyncpg://u:p@h/db")
    await db_module.init_analytics_db()
    assert called["create_all"] is False
