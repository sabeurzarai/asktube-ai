import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.analytics.database import build_engine_kwargs
from app.analytics.models import Base
from app.core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The app's settings are the single source of truth for the URL unless a caller
# overrode it explicitly (the migration test does exactly that).
if not config.get_main_option("sqlalchemy.url", None):
    # Alembic's Config wraps configparser.ConfigParser with BasicInterpolation,
    # which raises ValueError on a lone '%' -- and .env.example instructs users
    # to percent-encode passwords containing @ : / #, so any such password
    # crashes here unescaped. Escaping to %% is undone by ConfigParser's own
    # get() reader, so run_migrations_online()/offline() still see the correct,
    # unescaped URL. Do not "simplify" this away.
    config.set_main_option(
        "sqlalchemy.url", settings.resolved_analytics_url.replace("%", "%%")
    )

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
    # Reuse the app's own connect_args (statement_cache_size=0,
    # prepared_statement_cache_size=0, a UUID name func) so the migration
    # engine gets the same DuplicatePreparedStatementError protection as the
    # runtime engine in app/analytics/database.py -- NullPool alone (below)
    # only avoids Alembic's own connection pool, it does not touch asyncpg's
    # or SQLAlchemy's prepared-statement layers.
    connect_args = build_engine_kwargs(settings.resolved_analytics_url, settings).get(
        "connect_args"
    )
    engine_kwargs: dict[str, object] = {"poolclass": pool.NullPool}
    if connect_args:
        engine_kwargs["connect_args"] = connect_args

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        **engine_kwargs,
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
