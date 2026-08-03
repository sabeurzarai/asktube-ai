from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.services.vector_store.base import VectorStore
from app.services.vector_store.memory import InMemoryVectorStore
from app.services.vector_store.postgres import PgVectorStore


def create_vector_store(config: Settings) -> VectorStore:
    """Select the vector store backend.

    Resolution order:
      1. VECTOR_BACKEND, if set
      2. chroma — while ChromaVectorStoreService still exists

    Phase 2b-ii replaces rule 2 with the derived default (DATABASE_URL set →
    pgvector, else memory), once Chroma is gone and defaulting to it is no longer
    possible. Until then, an unset VECTOR_BACKEND must not change which backend
    production uses.
    """
    backend = (config.vector_backend or "chroma").lower()

    if backend == "memory":
        return InMemoryVectorStore()

    if backend == "pgvector":
        if not config.database_url:
            raise ValueError(
                "VECTOR_BACKEND=pgvector requires DATABASE_URL to be set."
            )
        engine = create_async_engine(
            config.database_url,
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
            pool_pre_ping=True,
            connect_args={"statement_cache_size": 0},
        )
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        return PgVectorStore(factory)

    if backend == "chroma":
        # Imported lazily: vectorstore_service imports this module's package, and a
        # top-level import here would be circular.
        from app.services.vectorstore_service import ChromaVectorStoreService

        return ChromaVectorStoreService(config)

    raise ValueError(
        f"Unknown VECTOR_BACKEND {backend!r}. Expected 'chroma', 'pgvector' or 'memory'."
    )
