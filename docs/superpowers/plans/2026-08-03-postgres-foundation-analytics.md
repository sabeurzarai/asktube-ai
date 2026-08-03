# Postgres Foundation + Analytics Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move analytics storage from in-container SQLite to managed Postgres, establishing the connection stack (pooling, asyncpg tuning, Alembic migrations) that later phases will reuse for vectors and conversation memory.

**Architecture:** A single `DATABASE_URL` becomes the one Postgres connection for all future stores. Analytics goes first because it is already SQLAlchemy and because it is fire-and-forget — if the connection configuration is wrong, it surfaces here rather than in the chat path. SQLite remains the default so local development and CI need no database.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, Postgres 15 (Supabase), pytest / pytest-asyncio in `auto` mode.

## Global Constraints

- Deployment must stay at **$0/month**. No paid services.
- **Defaults must preserve current behaviour.** With no new environment variables set, the app runs exactly as today on SQLite. Merging this plan changes nothing until the environment opts in.
- **Test-count baselines.** Two baselines exist and must not be confused: with local-embedding extras installed (this development machine) the suite reports **148 passed, 0 skipped**; without them, **144 passed, 4 skipped** as documented in `CLAUDE.md`. This plan adds **9 passing tests** plus **1 test that skips** unless `TEST_DATABASE_URL` is set. Final expected state on a machine with extras: **157 passed, 1 skipped**. New database-dependent tests skip, never fail.
- Frontend is untouched: `npx tsc --noEmit && npm test` must still report **79 passed**.
- Public API contract and response schemas are unchanged.
- Python 3.12, SQLAlchemy `2.0.36`, asyncpg `0.30.0` (both already in `backend/requirements.txt`).
- Never commit credentials. `DATABASE_URL` goes in Render's environment and `.env.example` gets a placeholder only.
- Work happens on branch `arch/state-consolidation-pgvector`. Do not push to `main`.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/core/config.py` | Add `DATABASE_URL`, pool sizing settings, and URL resolution |
| `backend/app/analytics/database.py` | Driver-aware engine construction; SQLite-only auto-create |
| `backend/app/analytics/models.py` | JSONB variant for `metadata_json` columns |
| `backend/alembic.ini` | Alembic configuration |
| `backend/alembic/env.py` | Async migration runner reading the app's settings |
| `backend/alembic/versions/0001_initial_analytics.py` | Initial analytics schema |
| `backend/tests/test_analytics_database.py` | Engine-kwargs and auto-create behaviour |
| `backend/tests/test_analytics_models.py` | Column type compilation per dialect |
| `backend/tests/test_migrations.py` | Alembic upgrade against a real database (skipped without `TEST_DATABASE_URL`) |

---

### Task 1: Single `DATABASE_URL` setting with pool tuning

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `Settings.database_url: str | None`, `Settings.db_pool_size: int`, `Settings.db_max_overflow: int`, and `Settings.resolved_analytics_url: str` (property). Tasks 2 and 5 depend on `resolved_analytics_url`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && python -m pytest tests/test_config.py -v
```
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'resolved_analytics_url'`.

- [ ] **Step 3: Implement the settings**

In `backend/app/core/config.py`, add these fields immediately after the existing `analytics_database_url` field:

```python
    database_url: str | None = Field(
        default=None,
        alias="DATABASE_URL",
        description=(
            "Single async SQLAlchemy URL for all persistent stores. When set it "
            "takes priority over ANALYTICS_DATABASE_URL. Example: "
            "postgresql+asyncpg://user:password@host:6543/postgres"
        ),
    )
    db_pool_size: int = Field(
        default=5,
        alias="DB_POOL_SIZE",
        description="Kept small: Supabase Free caps connections and Render's free container is memory-constrained.",
    )
    db_max_overflow: int = Field(
        default=5,
        alias="DB_MAX_OVERFLOW",
        description="Additional connections allowed beyond db_pool_size under burst.",
    )
```

Then add this property next to the existing `webshare_proxy_location_list` property:

```python
    @property
    def resolved_analytics_url(self) -> str:
        """DATABASE_URL wins; ANALYTICS_DATABASE_URL is the backwards-compatible fallback."""
        return self.database_url or self.analytics_database_url
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd backend && python -m pytest tests/test_config.py -v
```
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_config.py
git commit -m "feat: add DATABASE_URL and connection pool settings"
```

---

### Task 2: Driver-aware engine construction

Passing `pool_size` to a SQLite engine raises `TypeError` because aiosqlite uses a pool class that takes no size, and `statement_cache_size` is an asyncpg-only connect arg. So engine kwargs must branch on the driver rather than being applied unconditionally.

**Files:**
- Modify: `backend/app/analytics/database.py:9-13`
- Test: `backend/tests/test_analytics_database.py` (create)

**Interfaces:**
- Consumes: `Settings.resolved_analytics_url`, `Settings.db_pool_size`, `Settings.db_max_overflow` from Task 1.
- Produces: `build_engine_kwargs(url: str, config: Settings) -> dict[str, Any]`. Task 5 does not use it; nothing later depends on it beyond this module.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_analytics_database.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && python -m pytest tests/test_analytics_database.py -v
```
Expected: FAIL with `ImportError: cannot import name 'build_engine_kwargs'`.

- [ ] **Step 3: Implement the engine builder**

Replace lines 1–18 of `backend/app/analytics/database.py` with:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, settings


def build_engine_kwargs(url: str, config: Settings) -> dict[str, Any]:
    """Engine options per driver.

    SQLite's async pool takes no size, and statement_cache_size is an asyncpg-only
    connect arg, so neither can be applied unconditionally.
    """
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}

    if url.startswith("postgresql"):
        kwargs["pool_size"] = config.db_pool_size
        kwargs["max_overflow"] = config.db_max_overflow
        # Prepared statements do not survive a transaction pooler. Left enabled,
        # this fails intermittently with DuplicatePreparedStatementError under
        # concurrency rather than failing loudly at startup.
        kwargs["connect_args"] = {"statement_cache_size": 0}

    return kwargs


engine = create_async_engine(
    settings.resolved_analytics_url,
    **build_engine_kwargs(settings.resolved_analytics_url, settings),
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

Leave `analytics_session` and `init_analytics_db` below unchanged for now; Task 5 modifies the latter.

- [ ] **Step 4: Run the tests**

Run:
```bash
cd backend && python -m pytest tests/test_analytics_database.py tests/test_analytics_service.py -v
```
Expected: PASS. `test_analytics_service.py` must still pass — it patches `AsyncSessionLocal`, which still exists.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analytics/database.py backend/tests/test_analytics_database.py
git commit -m "feat: driver-aware engine kwargs for postgres and sqlite"
```

---

### Task 3: JSONB columns on Postgres

**Files:**
- Modify: `backend/app/analytics/models.py:4`, and the four `metadata_json` columns at lines 26, 40, 53, 72
- Test: `backend/tests/test_analytics_models.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `JSON_VARIANT` exported from `app.analytics.models`, used by the Task 4 migration.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_analytics_models.py`:

```python
from sqlalchemy.dialects import postgresql, sqlite

from app.analytics.models import AnalyticsEvent, ChatMetric, RAGMetric, VideoMetric


def test_metadata_json_compiles_to_jsonb_on_postgres():
    for model in (AnalyticsEvent, VideoMetric, ChatMetric, RAGMetric):
        column = model.__table__.c.metadata_json
        compiled = column.type.compile(dialect=postgresql.dialect())
        assert compiled == "JSONB", f"{model.__name__} should use JSONB on postgres"


def test_metadata_json_stays_json_on_sqlite():
    column = AnalyticsEvent.__table__.c.metadata_json
    assert column.type.compile(dialect=sqlite.dialect()) == "JSON"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && python -m pytest tests/test_analytics_models.py -v
```
Expected: FAIL — `assert 'JSON' == 'JSONB'`.

- [ ] **Step 3: Add the variant**

In `backend/app/analytics/models.py`, change the import on line 4 and add the variant beneath it:

```python
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB is indexable and typed on Postgres; SQLite keeps plain JSON so local
# development and the test suite are unaffected.
JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")
```

Then replace `JSON` with `JSON_VARIANT` in all four `metadata_json` column definitions:

```python
    metadata_json: Mapped[dict] = mapped_column(JSON_VARIANT, default=dict)
```

- [ ] **Step 4: Run the tests**

Run:
```bash
cd backend && python -m pytest tests/test_analytics_models.py tests/test_analytics_service.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analytics/models.py backend/tests/test_analytics_models.py
git commit -m "feat: use JSONB for analytics metadata on postgres"
```

---

### Task 4: Alembic migrations

`create_all` cannot express `CREATE EXTENSION vector` or an HNSW index, which Phase 2 needs, so migrations are introduced now while the schema is still simple.

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_initial_analytics.py`
- Test: `backend/tests/test_migrations.py` (create)

**Interfaces:**
- Consumes: `Settings.resolved_analytics_url` (Task 1), `JSON_VARIANT` and `Base` (Task 3).
- Produces: revision `0001` as the migration base. Phase 2's vector migration will set `down_revision = "0001"`.

- [ ] **Step 1: Add the dependency**

Append to `backend/requirements.txt`:

```
alembic==1.14.0
```

Install it:
```bash
cd backend && pip install alembic==1.14.0
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_migrations.py`:

```python
import os

import pytest

# Runs only when a real database is available. Mirrors the existing convention
# for local-embedding tests: absent extras/infrastructure means skip, not fail.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set; skipping migration test",
)


async def test_migrations_create_analytics_tables():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public'"
            )
        )
        tables = {row[0] for row in result}
    await engine.dispose()

    assert {"analytics_events", "video_metrics", "chat_metrics", "rag_metrics"} <= tables
```

- [ ] **Step 3: Run to verify it skips cleanly**

Run:
```bash
cd backend && python -m pytest tests/test_migrations.py -v
```
Expected: `1 skipped` — not an error. This proves the skip guard works before the migration exists.

- [ ] **Step 4: Create `backend/alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 5: Create `backend/alembic/env.py`**

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.analytics.models import Base
from app.core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The app's settings are the single source of truth for the URL unless a caller
# overrode it explicitly (the migration test does exactly that).
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", settings.resolved_analytics_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6: Create `backend/alembic/versions/0001_initial_analytics.py`**

```python
"""initial analytics schema

Revision ID: 0001
Revises:
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSON_VARIANT = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(120), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("session_id", sa.String(120), nullable=True, index=True),
        sa.Column("user_id", sa.String(120), nullable=True, index=True),
        sa.Column("page", sa.String(240), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("metadata_json", JSON_VARIANT, nullable=False),
    )
    op.create_table(
        "video_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("video_id", sa.String(40), nullable=False, index=True),
        sa.Column("processing_time", sa.Float(), nullable=False),
        sa.Column("transcript_time", sa.Float(), nullable=False),
        sa.Column("embedding_time", sa.Float(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("whisper_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("metadata_json", JSON_VARIANT, nullable=False),
    )
    op.create_table(
        "chat_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(120), nullable=False, index=True),
        sa.Column("questions_count", sa.Integer(), nullable=False),
        sa.Column("avg_response_time", sa.Float(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("followup_questions", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("metadata_json", JSON_VARIANT, nullable=False),
    )
    op.create_table(
        "rag_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("retrieval_latency", sa.Float(), nullable=False),
        sa.Column("generation_latency", sa.Float(), nullable=False),
        sa.Column("chunks_retrieved", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("citation_coverage", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("context_tokens", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("response_length", sa.Integer(), nullable=False),
        sa.Column("hallucination_warning", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", JSON_VARIANT, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rag_metrics")
    op.drop_table("chat_metrics")
    op.drop_table("video_metrics")
    op.drop_table("analytics_events")
```

- [ ] **Step 7: Verify migration generates valid SQL without a database**

Run:
```bash
cd backend && python -m alembic upgrade head --sql
```
Expected: prints `CREATE TABLE` statements for all four tables to stdout and exits 0. This validates the migration offline, with no database required.

- [ ] **Step 8: Run the full suite**

Run:
```bash
cd backend && python -m pytest -q
```
Expected: **155 passed, 1 skipped** on a machine with local-embedding extras (148 baseline + 7 tests added by Tasks 1–3; the migration test skips). Without extras: `151 passed, 5 skipped`.

- [ ] **Step 9: Commit**

```bash
git add backend/requirements.txt backend/alembic.ini backend/alembic backend/tests/test_migrations.py
git commit -m "feat: add alembic with initial analytics migration"
```

---

### Task 5: Auto-create only on SQLite

With Alembic owning the Postgres schema, leaving `create_all` active against Postgres means two mechanisms managing the same tables, which drifts silently.

**Files:**
- Modify: `backend/app/analytics/database.py:27-31`
- Test: `backend/tests/test_analytics_database.py` (extend)

**Interfaces:**
- Consumes: `build_engine_kwargs` module context from Task 2.
- Produces: `init_analytics_db()` with unchanged signature (`async def init_analytics_db() -> None`). `app/main.py` continues calling it as-is.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_analytics_database.py`:

```python
import app.analytics.database as db_module


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && python -m pytest tests/test_analytics_database.py -v
```
Expected: FAIL on `test_init_skips_create_all_on_postgres` with `AssertionError: create_all must not run against postgres`.

- [ ] **Step 3: Implement the guard**

Replace `init_analytics_db` at the bottom of `backend/app/analytics/database.py`:

```python
async def init_analytics_db() -> None:
    """Create tables automatically for local SQLite only.

    Postgres schema is owned by Alembic. Running create_all there as well would
    mean two mechanisms managing one schema, which drifts without warning.
    """
    if settings.resolved_analytics_url.startswith("postgresql"):
        return

    from app.analytics.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
```

- [ ] **Step 4: Run the tests**

Run:
```bash
cd backend && python -m pytest tests/test_analytics_database.py -v
```
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analytics/database.py backend/tests/test_analytics_database.py
git commit -m "feat: leave postgres schema to alembic, auto-create sqlite only"
```

---

### Task 6: Documentation and environment template

**Files:**
- Modify: `.env.example`, `CLAUDE.md`, `AGENTS.md`, `DEMO_DAY_RUNBOOK.md`, `LEARNINGS.md`

**Interfaces:**
- Consumes: every setting introduced in Task 1.
- Produces: nothing consumed by code.

- [ ] **Step 1: Add the variables to `.env.example`**

Append, keeping the placeholder-only convention already used in that file:

```bash
# ── Database ──────────────────────────────────────────────────────────────
# Single async SQLAlchemy URL for all persistent stores. Unset = SQLite
# (current behaviour). Supabase gives this in Project Settings → Database.
# The password must be percent-encoded if it contains @ : / or #.
# Port 6543 is the Supavisor transaction pooler; 5432 is a direct connection.
# DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@db.PROJECT.supabase.co:6543/postgres
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
```

- [ ] **Step 2: Document the configuration in `CLAUDE.md` and `AGENTS.md`**

Add to the "Configuration" section of both files (they are kept in sync):

```markdown
- Database: `DATABASE_URL` is the single async SQLAlchemy URL for all persistent
  stores and takes priority over `ANALYTICS_DATABASE_URL`. Unset, everything runs
  on SQLite as before. Postgres schema is owned by Alembic (`cd backend && python
  -m alembic upgrade head`); `init_analytics_db()` auto-creates tables for SQLite
  only. When using Supabase's transaction pooler (port 6543), `statement_cache_size`
  is forced to 0 — asyncpg's prepared statements do not survive a transaction
  pooler and fail intermittently under concurrency.
```

- [ ] **Step 3: Add the restore step to `DEMO_DAY_RUNBOOK.md`**

Add to step 0, next to the existing Render warm-up:

```markdown
- If `DATABASE_URL` points at Supabase: confirm the project is not paused
  (Free plan pauses after 7 days of low activity and needs a manual restore from
  the dashboard). A paused database surfaces as a 502 on ingest and chat.
```

- [ ] **Step 4: Record the pooler lesson in `LEARNINGS.md`**

Add as the newest bullet at the top:

```markdown
- **2026-08-03** — Supabase Free pauses a project after 7 days of low activity and
  requires a MANUAL restore; paused beyond 90 days it is deleted permanently. Neon
  behaves differently (5-minute scale-to-zero, automatic resume) — if the demo goes
  unused for weeks, that difference matters more than any latency number. Also:
  asyncpg caches prepared statements, which a transaction pooler (Supabase port
  6543) cannot carry — set `statement_cache_size=0` or hit intermittent
  `DuplicatePreparedStatementError` under concurrency, never at startup.
```

- [ ] **Step 5: Verify the full suite is unaffected**

Run:
```bash
cd backend && python -m pytest -q
```
Expected: **157 passed, 1 skipped** with extras (all 9 new tests now present); `153 passed, 5 skipped` without.

- [ ] **Step 6: Commit**

```bash
git add .env.example CLAUDE.md AGENTS.md DEMO_DAY_RUNBOOK.md LEARNINGS.md
git commit -m "docs: document DATABASE_URL, alembic workflow and supabase pause"
```

---

### Task 7: End-to-end verification against the real database

This is the task the whole phase exists for: proving the connection stack works before Phase 2 depends on it.

**Files:** none modified. Verification only.

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: a verified `DATABASE_URL` configuration for Render, and confirmation that the pooler settings are correct.

- [ ] **Step 1: Run the migration against Supabase**

Obtain the connection string from Supabase → Project Settings → Database → Connection string → URI, converting the scheme to `postgresql+asyncpg://` and percent-encoding the password.

```bash
cd backend && DATABASE_URL="postgresql+asyncpg://postgres:ENCODED@db.yskjultqsrbikvmyvwnu.supabase.co:6543/postgres" python -m alembic upgrade head
```
Expected: `Running upgrade  -> 0001, initial analytics schema`.

- [ ] **Step 2: Confirm the tables exist**

In the Supabase dashboard → Table Editor, confirm `analytics_events`, `video_metrics`, `chat_metrics` and `rag_metrics` are present with `metadata_json` typed `jsonb`.

- [ ] **Step 3: Run the database-backed tests**

```bash
cd backend && TEST_DATABASE_URL="postgresql+asyncpg://postgres:ENCODED@db.yskjultqsrbikvmyvwnu.supabase.co:6543/postgres" python -m pytest tests/test_migrations.py -v
```
Expected: PASS — the previously skipped test now runs.

- [ ] **Step 4: Boot the app against Postgres and exercise analytics**

```bash
cd backend && DATABASE_URL="postgresql+asyncpg://postgres:ENCODED@db.yskjultqsrbikvmyvwnu.supabase.co:6543/postgres" OPENAI_API_KEY=dummy python -m uvicorn app.main:app --port 8000
```

In a second shell:
```bash
curl -s http://localhost:8000/health
curl -s -X POST http://localhost:8000/api/analytics/events -H "Content-Type: application/json" -d '{"event_type":"smoke_test","page":"/plan-verification"}'
curl -s http://localhost:8000/api/analytics/dashboard
```
Expected: `/health` returns `{"status":"ok",...}`; the event POST is accepted; the dashboard reflects the event. Confirm the row appears in Supabase's Table Editor.

- [ ] **Step 5: Set the variable on Render**

In the Render dashboard for `asktube-ai`, add `DATABASE_URL` with the same value. Do not commit it. Trigger a deploy and confirm `/health` still returns 200 afterwards.

- [ ] **Step 6: Final verification and commit**

```bash
cd backend && python -m pytest -q
cd ../frontend && npx tsc --noEmit && npm test
```
Expected: backend **157 passed, 1 skipped** with extras (`153 passed, 5 skipped` without); frontend **79 passed**.

```bash
git commit --allow-empty -m "chore: verify postgres analytics end to end"
```

---

## Deliberately deferred from this phase

**The paused-database error message.** The spec requires connection failure to
return a message naming the likely cause ("database unreachable — a paused Supabase
project must be restored"), modelled on commit `b1e3a3d`. It is not implemented
here, because in this phase there is no user-facing path to attach it to: analytics
is fire-and-forget by design, so a failed connection is swallowed and logged and
never reaches a response. The message belongs on the first request path that fails
loudly, which is the vector store in Phase 2. Task 6 covers the operational half of
the same risk now, via the runbook check.

## Phases not covered by this plan

- **Phase 2 — vectors on pgvector.** `VectorStore` protocol, `transcript_chunks` table, HNSW index, `VECTOR_BACKEND` flag, contract tests over both backends. Its migration sets `down_revision = "0001"`.
- **Phase 3 — conversation memory on Postgres.** `ConversationStore` protocol, `conversation_messages` table, `MEMORY_BACKEND` flag, and the async refactor of every `get_messages` / `append_exchange` call site.

Each gets its own plan after this one is verified against the real database.
