from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.services.conversation_store.base import ConversationStore
from app.services.conversation_store.memory import InMemoryConversationStore
from app.services.conversation_store.postgres import PostgresConversationStore


def resolve_conversation_backend(config: Settings) -> str:
    """Explicit CONVERSATION_BACKEND wins; otherwise derive from DATABASE_URL.

    Deriving rather than defaulting to "memory" is deliberate: forgetting the
    variable in a deployment that has a database would otherwise start an
    in-process store that loses every conversation on restart and looks like it
    is working.
    """
    if config.conversation_backend:
        return config.conversation_backend.lower()
    return "postgres" if config.database_url else "memory"


def create_conversation_store(config: Settings) -> ConversationStore:
    backend = resolve_conversation_backend(config)

    if backend == "memory":
        return InMemoryConversationStore()

    if backend == "postgres":
        if not config.database_url:
            raise ValueError(
                "CONVERSATION_BACKEND=postgres requires DATABASE_URL to be set."
            )
        engine = create_async_engine(
            config.database_url,
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
            pool_pre_ping=True,
            # Prepared statements do not survive a transaction pooler; left enabled
            # this fails intermittently under concurrency rather than at startup.
            connect_args={"statement_cache_size": 0},
        )
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        return PostgresConversationStore(factory)

    raise ValueError(
        f"Unknown CONVERSATION_BACKEND {backend!r}. Expected 'postgres' or 'memory'."
    )
