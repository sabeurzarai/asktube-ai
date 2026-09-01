from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.analytics.database import build_engine_kwargs

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
        # Shared options - see the note in vector_store/factory.py. This engine
        # had the same drift: one of the three required asyncpg connect args.
        engine = create_async_engine(
            config.database_url,
            **build_engine_kwargs(config.database_url, config),
        )
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        return PostgresConversationStore(factory)

    raise ValueError(
        f"Unknown CONVERSATION_BACKEND {backend!r}. Expected 'postgres' or 'memory'."
    )
